# These files are packaged for reference only. They are never executed by the
# RPA runner, so a documentation encoding or transfer change must not prevent
# the desktop application from starting.
UNPROTECTED_DOCUMENTATION = frozenset({
    "README.txt",
    "用户操作说明.md",
})


PROTECTED_SHA256 = {
    "build_exe.ps1": "a998521019b0f239463eb50db04b5febfc52b38b24e4a67a5ad854f6164c77b5",
    "etax_batch_export.py": "a214ee410cfa5312f7d674e4cbdf0ceec2506478e7ec44be68678ab766e0155b",
    "etax_batch_import.py": "df475c51c7acf31be184b41db02a0851c17449f9b1de3b277a9cd027115ee773",
    "etax_gui.py": "dcd68e4ceb5b6cfda507b98e9c627b0085ffa9435d132b8a24a8d9cc03614640",
    "etax_tax_certificate_download.py": "553dcdae0ed0d515287662aa70ccd2ff7bee2922f32a08e56a4efde680f70645",
    "requirements(1).txt": "0fc694270c95e312f5faaaa63869af1e06f409de070600d20d0c4d6b3deb65a4",
    "start_debug_chrome.ps1": "3ff42a6978821b230be03fe1de1c191b7103ef2b00752e9c522f4ebe51320826",
    "start_gui.ps1": "3950132ef07e7e5660be7062bcb5ac73ebb394853b22310d51bff69993444b44",
}
