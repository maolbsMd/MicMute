# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置: 生成单文件便携版 MicMute.exe (PyQt6 + Fluent UI)

用法:
    pyinstaller MicMute.spec --noconfirm
生成的可执行文件位于 dist\\MicMute.exe, 可直接拷贝到任意 Windows 机器运行
(无需安装 Python)。配置文件 micmute_settings.json 会保存在 exe 同目录。
"""
import os

block_cipher = None

# 将 micmute.ico 一并放入 datas 以保证 _MEIPASS 中可访问
datas = []
ico_path = os.path.join(os.path.dirname(SPEC), 'micmute.ico')
if os.path.exists(ico_path):
    datas.append((ico_path, '.'))

a = Analysis(
    ['micmute.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # pycaw / comtypes 动态加载的 COM 接口
        'comtypes',
        'comtypes.client',
        'pycaw.pycaw',
        'pycaw.constants',
        'pycaw.api.mmdeviceapi',
        'pycaw.api.endpointvolume',
        'pycaw.api.audioclient',
        # pynput Windows 后端
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # PyQt6 子模块 (PyInstaller 偶尔会漏)
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtSvg',
        # qfluentwidgets 主题/资源
        'qfluentwidgets',
        'qfluentwidgets.components',
        'qfluentwidgets.window',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 精简体积: 排除不用的大型库
        # 注意: numpy / scipy / PyQt6.QtXml 是 qfluentwidgets 的强依赖
        # (Acrylic 模糊), 不能排除, 否则 exe 启动报缺包。
        'matplotlib', 'pytest', 'unittest',
        'PyQt6.Qt3DCore', 'PyQt6.Qt3DRender', 'PyQt6.Qt3DExtras',
        'PyQt6.QtBluetooth', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtNetwork', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtPositioning',
        'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D',
        'PyQt6.QtQuickWidgets', 'PyQt6.QtRemoteObjects',
        'PyQt6.QtScxml', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort',
        'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets', 'PyQt6.QtXmlPatterns',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MicMute',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ico_path if os.path.exists(ico_path) else None,
)
