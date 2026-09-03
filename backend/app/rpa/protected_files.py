# These files are packaged for reference only. They are never executed by the
# RPA runner, so a documentation encoding or transfer change must not prevent
# the desktop application from starting.
UNPROTECTED_DOCUMENTATION = frozenset({
    "README.txt",
    "用户操作说明.md",
})


PROTECTED_SHA256 = {
    "build_exe.ps1": "a998521019b0f239463eb50db04b5febfc52b38b24e4a67a5ad854f6164c77b5",
    "etax_batch_export.py": "78942e5bf64a94e8b7e0fd90e13f1a5b3bf2ecef320f6a0c36a1fdce83d808f6",
    "etax_batch_import.py": "f121831b243a8f2805b151cee568365235f6d2c0897309ba6b47fa5a900978e8",
    "etax_gui.py": "dcd68e4ceb5b6cfda507b98e9c627b0085ffa9435d132b8a24a8d9cc03614640",
    "etax_tax_certificate_download.py": "425e890bca29eaaf8f6823293378b7d1905fbed2b7c1a062f7e29fc916809dfe",
    "requirements(1).txt": "0fc694270c95e312f5faaaa63869af1e06f409de070600d20d0c4d6b3deb65a4",
    "start_debug_chrome.ps1": "3ff42a6978821b230be03fe1de1c191b7103ef2b00752e9c522f4ebe51320826",
    "start_gui.ps1": "3950132ef07e7e5660be7062bcb5ac73ebb394853b22310d51bff69993444b44",
}
