# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 鎵撳寘閰嶇疆: 鐢熸垚鍗曟枃浠朵究鎼虹増 MicMute.exe (PyQt6 + Fluent UI)

鐢ㄦ硶:
    pyinstaller MicMute.spec --noconfirm
鐢熸垚鐨勫彲鎵ц鏂囦欢浣嶄簬 dist\\MicMute.exe, 鍙洿鎺ユ嫹璐濆埌浠绘剰 Windows 鏈哄櫒杩愯
(鏃犻渶瀹夎 Python)銆傞厤缃枃浠?micmute_settings.json 浼氫繚瀛樺湪 exe 鍚岀洰褰曘€?"""
import os

block_cipher = None

# 灏?micmute.ico 涓€骞舵斁鍏?datas 浠ヤ繚璇?_MEIPASS 涓彲璁块棶
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
        # pycaw / comtypes 鍔ㄦ€佸姞杞界殑 COM 鎺ュ彛
        'comtypes',
        'comtypes.client',
        'pycaw.pycaw',
        'pycaw.constants',
        'pycaw.api.mmdeviceapi',
        'pycaw.api.endpointvolume',
        'pycaw.api.audioclient',
        # pynput Windows 鍚庣
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # PyQt6 瀛愭ā鍧?(PyInstaller 鍋跺皵浼氭紡)
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtSvg',
        # qfluentwidgets 涓婚/璧勬簮
        'qfluentwidgets',
        'qfluentwidgets.components',
        'qfluentwidgets.window',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 绮剧畝浣撶Н: 鎺掗櫎涓嶇敤鐨勫ぇ鍨嬪簱
        # 娉ㄦ剰: numpy / scipy / PyQt6.QtXml 鏄?qfluentwidgets 鐨勫己渚濊禆
        # (Acrylic 妯＄硦), 涓嶈兘鎺掗櫎, 鍚﹀垯 exe 鍚姩鎶ョ己鍖呫€?        'matplotlib', 'pytest', 'unittest',
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
    name='MicMute_debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                 # 鏃犳帶鍒跺彴绐楀彛
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ico_path if os.path.exists(ico_path) else None,
)

