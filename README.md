# sidestick-edit

## Windows 快捷启动

双击项目目录中的 `start.bat` 即可启动。首次运行时需要电脑已安装 Python 3 并能联网；脚本会在项目目录下创建 `.venv`，并自动安装 `requirements.txt` 中的依赖。后续启动会复用该环境；如果环境失效（例如复制了另一台电脑的 `.venv`），脚本会自动重建。

如果提示找不到 Python，请安装 Python 3，并在安装时勾选 **Add Python to PATH**。脚本也会检查当前用户默认的 Python 安装目录。要在另一台电脑上运行，请复制整个项目目录（无需复制 `.venv`），然后在该电脑上双击 `start.bat`。
