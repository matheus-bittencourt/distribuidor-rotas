# PyInstaller: pyinstaller distribuidor.spec  ->  dist/DistribuidorRotas/ (pasta, não arquivo único:
# o modo arquivo único se descompacta em %TEMP% a cada execução e deixaria rastro no computador).
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("app/static", "app/static"), ("app/zones.json", "app"), ("app/pedestrian_zone.json", "app")]
binaries, hidden = [], []
for pkg in ("ortools", "uvicorn"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += collect_submodules("app") + ["openpyxl", "pypdf", "cryptography", "multipart", "python_multipart"]

a = Analysis(
    ["distribuidor.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["anthropic", "pandas", "matplotlib", "tkinter", "pytest", "IPython", "osmium", "pmtiles"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DistribuidorRotas", console=True,
          icon=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DistribuidorRotas")
