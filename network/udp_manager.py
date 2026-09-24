# -*- coding: utf-8 -*-
"""udp_manager —— 单 socket UDP 收发（后台线程）+ 看门狗（连接指示用，不门控发送）。

要点（决策 13/14，常量硬编码不配置）：
    - 本机只开**一个** UDP socket（Python socket.SOCK_DGRAM），绑定 (local_ip, local_port)，
      收发共用；后台线程持有 socket，backend 通过线程安全队列跨线程投递待发包。
    - 接收：循环 drain 积压，**只保留最新一帧** emit frame_received。
    - 看门狗：5.0s 没收到任何数据 → link_changed(False)；恢复收包 → True。
    - 发送：事件驱动单发（sendto），失败 emit socket_error，不重试（backend 侧无条件直发，UDP 无连接）。

为什么用标准库 socket + threading，而不是 Qt 的 QUdpSocket + QThread：
    PyQt5 5.15.x 在 Windows 下把 QUdpSocket 放进 QThread 里收包会**间歇性原生崩溃**
    （访问违规，进程直接退出，faulthandler 抓不到栈），且 thread.start() 后 socket
    绑定是异步的，存在启动竞态（早发帧/早收帧丢失）。改用标准库 socket + threading，
    绑定在 _run 里同步完成（start() 用 Event 等绑定就绪），规避以上两个问题。
    Qt 信号从普通 Python 线程 emit 是线程安全的（PyQt 自动队列连接投递到主线程）。

纯 Qt（QObject + pyqtSignal），无 QUdpSocket。
"""

import queue
import select
import socket
import threading
import time

from PyQt5.QtCore import QObject, pyqtSignal

#: 看门狗：超过该秒数没收到数据 → 断链
WATCHDOG_TIMEOUT_S = 5.0
#: 收包轮询间隔（秒）：决定发包延迟上限与看门狗检查粒度
POLL_INTERVAL_S = 0.01
#: 收包缓冲（远大于周期帧）
RECV_BUFFER = 65535


class UdpManager(QObject):
    """backend 看到的 UDP 门面：start/stop + send_datagram + 三个信号。

    - frame_received(bytes)：最新一帧周期回传（16B = 每通道 8B × 2 通道）
    - link_changed(bool)：看门狗连/断链
    - socket_error(str)：绑定/发送失败
    """

    frame_received = pyqtSignal(bytes)
    link_changed = pyqtSignal(bool)
    socket_error = pyqtSignal(str)

    def __init__(self, local_ip: str, local_port: int,
                 target_ip: str, target_port: int, parent=None):
        super().__init__(parent)
        self._local = (str(local_ip), int(local_port))
        self._target = (str(target_ip), int(target_port))
        self._out = queue.Queue()
        self._running = threading.Event()
        self._bound = threading.Event()
        self._thread = None

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._bound.clear()
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="udp-manager",
                                        daemon=True)
        self._thread.start()
        # 等 socket 绑定就绪，消除启动竞态（早发帧/早收帧不再丢失）
        self._bound.wait(timeout=2.0)

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def send_datagram(self, data: bytes):
        """线程安全：入队，由后台线程 sendto（不做重试）。"""
        self._out.put(bytes(data))

    # ------------------------------------------------------------
    # 运行时重连（菜单「设置→网络绑定…」）
    # ------------------------------------------------------------
    @staticmethod
    def probe_bind(local_ip: str, local_port: int) -> "Optional[str]":
        """同步试绑本地地址，返回错误文案；None = 可绑定。试完即关，不占端口。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((str(local_ip), int(local_port)))
        except OSError as exc:
            return "本机 %s:%d 绑定失败：%s" % (local_ip, local_port, exc)
        finally:
            sock.close()
        return None

    def reconfig(self, local_ip: str, local_port: int,
                 target_ip: str, target_port: int):
        """运行中改地址并立即生效：停旧线程 → 换址 → 重启绑定。

        主线程（UI）调用。stop() 已 join 旧线程，无并发绑定竞态；
        先 emit link_changed(False) 复位链路灯，新线程收帧后再置绿。
        """
        self.stop()
        self.link_changed.emit(False)
        self._local = (str(local_ip), int(local_port))
        self._target = (str(target_ip), int(target_port))
        self.start()

    # ------------------------------------------------------------
    # 后台线程
    # ------------------------------------------------------------
    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(self._local)
        except OSError as exc:
            self._bound.set()
            self.link_changed.emit(False)
            self.socket_error.emit("绑定 %s:%d 失败：%s"
                                   % (self._local[0], self._local[1], exc))
            return
        sock.setblocking(False)
        self._bound.set()

        connected = False
        last_rx = time.monotonic()
        try:
            while self._running.is_set():
                self._drain_send(sock)
                ready, _, _ = select.select([sock], [], [], POLL_INTERVAL_S)
                now = time.monotonic()
                if ready and self._drain_recv(sock):
                    last_rx = now
                    if not connected:
                        connected = True
                        self.link_changed.emit(True)
                if connected and (now - last_rx) > WATCHDOG_TIMEOUT_S:
                    connected = False
                    self.link_changed.emit(False)
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _drain_send(self, sock):
        while True:
            try:
                pkt = self._out.get_nowait()
            except queue.Empty:
                return
            try:
                print("[UDP TX] target=%s:%d bytes=%d" %
                      (self._target[0], self._target[1], len(pkt)))
                sock.sendto(pkt, self._target)
            except OSError as exc:
                self.socket_error.emit("发送失败（%d 字节）：%s" % (len(pkt), exc))

    def _drain_recv(self, sock):
        """读光当前积压，只保留最新一帧并 emit。返回是否收到帧。"""
        last = None
        while True:
            try:
                data, _ = sock.recvfrom(RECV_BUFFER)
            except BlockingIOError:
                break
            except OSError:
                # Windows WSAECONNRESET（对不可达目标 sendto 后）等：忽略继续
                break
            last = bytes(data)
        if last is not None:
            self.frame_received.emit(last)
            return True
        return False

