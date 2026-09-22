class FmssError(Exception):
    user_message = "FMSS连接失败，请稍后重试。"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        if message:
            self.user_message = message


class FmssNotAuthenticated(FmssError):
    user_message = "FMSS登录已失效，请重新登录。"


class FmssPermissionDenied(FmssError):
    user_message = "当前FMSS账号没有执行该操作的权限。"


class FmssApiError(FmssError):
    def __init__(self, message: str = "FMSS接口返回异常") -> None:
        super().__init__(message)
        self.user_message = message or self.user_message


class FmssTemplateChanged(FmssError):
    user_message = "FMSS个税底稿模板已变化，请升级客户端映射后再提交。"


class FmssStateConflict(FmssError):
    pass


class FmssImportFailed(FmssError):
    pass


class FmssSubmitFailed(FmssError):
    pass


class FmssDecisionFailed(FmssError):
    pass


class FmssWriteDisabled(FmssError):
    user_message = "FMSS写入功能未启用。"


class FmssWriteContractUnavailable(FmssError):
    user_message = "FMSS写入报文尚未完成实测确认，当前客户端不会发送写请求。"


class FmssWriteUnknownResult(FmssError):
    user_message = "FMSS写请求结果未知，系统已停止重复提交，请刷新线上状态确认。"
