# FMSS 个税接口实测契约

测试时间：2026-09-22

测试范围：已登录 FMSS DEV 站点后的浏览器实测。已执行 PRE Excel 导入；按用户授权也尝试执行 POST Excel 导入，但服务端因缴款前未审核通过而拒绝。没有执行保存草稿、提交审核、审核通过、退回或撤回。

## 本次 DEV 浏览器实测记录（2026-09-22）

测试上下文：分公司 `19020`（成都分公司），期间 `2026-07`。以下只记录接口结构、状态和数量，不记录 Authorization、Cookie、OA 会话或业务明细原文。

### 1. PRE 查询

浏览器实际请求：

```text
GET /fmss/prod-api/iit/declaration?branchCode=19020&month=2026-07&stage=PRE
```

响应 HTTP `200`、业务 `code=200`。本次 PRE 导入后回读结果：

```json
{
  "document": {
    "id": 2,
    "branch_code": "19020",
    "tax_month": "2026-07",
    "stage": "PRE",
    "status": "DRAFT"
  },
  "canReturn": false,
  "canReimport": false
}
```

### 2. PRE Excel 导入

使用本地测试文件通过页面“批量导入 Excel”执行，实际请求为：

```text
POST /fmss/prod-api/iit/import
Content-Type: multipart/form-data; boundary=<浏览器自动生成>
```

表单字段确认存在：`branchCode=19020`、`month=2026-07`、`stage=PRE`、`file`。响应 HTTP `200`、业务 `code=200`、`msg=操作成功`，返回申报单 `id=2`，总导入 `217` 行，8 张 Sheet 均 `skipped=0`：

| Sheet | imported | skipped |
| --- | ---: | ---: |
| 汇总税额核对 | 17 | 0 |
| 申报表汇总数 | 41 | 0 |
| 个税明细税额核对 | 68 | 0 |
| 其他个税发生额核对 | 85 | 0 |
| 附A1 工资薪金等个税差异 | 2 | 0 |
| 附A2 累计应纳税所得额差异明细 | 4 | 0 |
| 附A3 客户利息个税差异明细 | 0 | 0 |
| 附A4 限售股个税差异明细 | 0 | 0 |

导入完成后页面自动再次调用 declaration，确认当前单据仍为 `id=2`、`status=DRAFT`。本次没有继续调用 submit。

### 3. POST 查询

浏览器实际请求：

```text
GET /fmss/prod-api/iit/declaration?branchCode=19020&month=2026-07&stage=POST
```

响应 HTTP `200`、业务 `code=200`，当前单据为 `id=3`、`status=DRAFT`、`canReturn=false`、`canReimport=false`。返回四个实际工作表 key 及行数：

```text
iit_post_tax_check      17
iit_post_certificate    86
iit_post_bank_flow      292
iit_post_bank_tax       17
```

### 4. POST Excel 导入前置校验

使用缴款后测试 Excel 通过页面发起导入，实际请求同样为 `POST /fmss/prod-api/iit/import`，`stage=POST`。服务端返回业务 `code=500`，未返回 `documents` 或 Sheet 导入结果：

```text
19020分公司导入失败：缴款前审核通过后才能编辑缴款后底稿
```

结论：POST 导入的“缴款前已 APPROVED”前置条件由 FMSS 服务端强制执行；本次没有改变 POST 数据，也没有继续提交。

### 5. PRE Sheets 动态定义

本次页面实际触发并收到 `GET /iit/sheets?stage=PRE`，响应 `code=200`，共 8 个对象。每个对象为 `{key,title,headers}`，`headers` 为纯中文字符串数组，不带 `key/label/type`。完整返回样例见本文后续 PRE Sheets 小节。

### 6. 审批日志

点击页面“审批日志”实际触发 `GET /fmss/prod-api/iit/approval-log`，响应 `code=200`，返回 `15` 条记录；本次返回的 `approvalStatus` 去重值为 `RETURNED`、`WITHDRAWN`、`APPROVED`。浏览器请求 URL 未带 query 参数，服务端按当前登录权限返回可见范围；文档中的 `branchCode/month` 仍应作为客户端代理接口的可选筛选参数保留。

### 7. 本轮登录账号的权限边界

本轮浏览器登录的是税务岗账号。该账号可完成查询和缴款前底稿导入，但不是复核岗，因此本轮不把复核、退回、审核通过和缴款后提交当作可测项。页面中对应审核按钮为禁用状态，属于权限结果，不代表接口不存在。后续复核接口由审核岗账号实测后再按真实返回补充。

本轮只做了一次只读查询验收：`19020` 成都分公司、`2026-07`，页面查询正常返回；没有新增写入操作。令牌、Cookie、OA 会话和业务明细原文均不记录。

## 认证与网关

- 实测页面：`https://fmssdev.gf.com.cn/fmss/trip/iitDeclaration/preReview`
- 实测网关：`/fmss/prod-api`。不要根据 `fmssdev` 域名推断为 `/fmss/dev-api`，网关前缀必须配置化。
- 实测认证：`Authorization: Bearer <token>`；当前令牌长度为 184 字符，未读取、记录或输出明文。
- `GET /iit/declaration?branchCode=19020&month=2026-07&stage=PRE` 返回 HTTP 200，响应信封为 `{ code, msg, data }`。

## `/iit/sheets?stage=PRE` 实测返回

结论：每个工作表对象为 `{ key, title, headers }`；`headers` 是纯中文字符串数组，没有 `key`、`label` 或 `type` 元数据。

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": [
    {
      "key": "iit_pre_tax_summary",
      "title": "汇总税额核对",
      "headers": ["机构代码", "营业部简称", "税款所属期", "申报表", "科目余额表期末余额", "申报表与余额表差异金额1", "差异原因1", "申报表与工资表、支撑平台差异金额2", "差异原因2", "当期工资薪金累计应纳税所得额差异金额3", "差异原因3", "经纪人支出当期发生额与工资表差异金额6", "差异原因6", "部分税种发生额差异金额7", "差异原因7"]
    },
    {
      "key": "iit_pre_filing_summary",
      "title": "申报表汇总数",
      "headers": ["机构代码", "营业部名称", "申报类型", "所得项目", "填写人次", "收入合计（元）", "应补/退税额（元）"]
    },
    {
      "key": "iit_pre_tax_detail",
      "title": "个税明细税额核对",
      "headers": ["机构代码", "营业部名称", "会计科目", "描述", "期初余额", "借方金额", "贷方金额", "期末余额", "申报表税额", "本期差异金额8（申报表-余额表贷方）", "差异原因8", "累计差异金额9（申报表-余额表期末余额）", "差异原因9", "工资表、支撑平台税额", "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）", "差异金额10（申报表-工资表、支撑平台税额）", "差异原因10"]
    },
    {
      "key": "iit_pre_other_tax",
      "title": "其他个税发生额核对",
      "headers": ["机构代码", "营业部名称", "会计科目", "描述", "对应税种", "期初余额", "借方金额", "贷方金额", "期末余额", "科目余额表当期发生额", "经纪人工资表应发", "差异金额11（工资表应发-余额表发生额）", "差异原因11", "发生额应申报收入", "发生额应申报收入说明", "申报表申报收入", "差异金额12（申报表申报收入-应申报收入）", "差异原因12"]
    },
    {
      "key": "iit_pre_appendix_a1",
      "title": "附A1 工资薪金等个税差异",
      "headers": ["机构代码", "机构简称", "期间", "姓名", "申报税额", "工资表税额", "差异金额", "差异原因"]
    },
    {
      "key": "iit_pre_appendix_a2",
      "title": "附A2 累计应纳税所得额差异明细",
      "headers": ["机构代码", "姓名", "累计应纳税所得额差异（工资表-申报表）", "累计专项扣除差异（工资表-申报表）", "累计专项附加扣除差异（含个人养老金）（工资表-申报表）", "其它差异（工资表-申报表）", "申报表税率", "应纳税额差异（工资表-申报表）", "差异原因"]
    },
    {
      "key": "iit_pre_appendix_a3",
      "title": "附A3 客户利息个税差异明细",
      "headers": ["机构代码", "营业部名称", "客户姓名", "证件号码", "债券利息收入", "兑息扣税", "申报税额", "差异金额", "差异原因"]
    },
    {
      "key": "iit_pre_appendix_a4",
      "title": "附A4 限售股个税差异明细",
      "headers": ["机构代码", "营业部名称", "客户姓名", "证件号码", "证券名称", "转让收入额", "利息税", "申报税额", "差异金额", "差异原因"]
    }
  ]
}
```

## `/iit/sheets?stage=POST` 实测返回

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": [
    {
      "key": "iit_post_tax_check",
      "title": "缴税核对",
      "headers": ["机构代码", "营业部全称", "申报表", "完税证明", "申报表与完税证明差异金额11", "差异原因11", "银行流水个税", "完税证明与银行流水差异金额11", "差异原因11"]
    },
    {
      "key": "iit_post_certificate",
      "title": "个税完税凭证",
      "headers": ["证明类型", "文件名", "纳税人名称", "纳税人识别号", "税种", "品目", "税款所属时期", "入(退)库日期", "实缴（退）金额"]
    },
    {
      "key": "iit_post_bank_flow",
      "title": "银行流水",
      "headers": ["查询账号", "查询开始日期", "查询结束日期", "来源页码", "账户名称", "账户币种", "币种名称", "银行代码", "本方账号", "本方户名", "交易时间", "借贷标志", "交易金额", "借方金额", "贷方金额", "交易摘要", "交易流水号", "余额", "币种", "对方账号", "对方户名", "手续费", "交易状态", "回单流水号", "序号", "日期", "时间", "sourceAccountNum", "sourceAreaCode"]
    },
    {
      "key": "iit_post_bank_tax",
      "title": "银行流水个税税额明细",
      "headers": ["机构代码", "营业部全称", "本方账号", "交易时间", "交易摘要", "借方金额"]
    }
  ]
}
```

## 已确认写接口（2026-09-22 补充）

以下结构来自已脱敏的真实请求样例。认证仍只使用 `Authorization: Bearer <token>`；Cookie、OA 会话和任何令牌明文均不记录、不持久化。

### Excel 导入

```text
POST /iit/import
Content-Type: multipart/form-data (由 HTTP 客户端生成 boundary)
```

字段：`branchCode`、`month`、`stage`（`PRE` 或 `POST`）、`file`。成功响应信封仍为 `{ code, msg, data }`。`data.documents` 包含申报单；`data.sheets` 按工作表标题返回 `{ imported, skipped }`；`data.totalImported` 为总导入量。任一 sheet 的 `skipped > 0` 时，客户端停止自动 submit。

导入后必须 `GET /iit/declaration` 回读，同一机构、所属期、阶段须返回相同单据 ID 且状态为 `DRAFT`，才允许继续提交。

### 提交审核

```text
POST /iit/submit
Content-Type: application/json;charset=UTF-8
```

```json
{"id": 2, "reviewer": "FMSS用户名"}
```

`data` 的数字只视为服务端附加值，不解释为 approval/todo ID。提交后必须回读单据，只有 `status=REVIEWING` 才视为成功。

### 审核决定

```text
POST /iit/decision
Content-Type: application/json;charset=UTF-8
```

```json
{"id": 2, "pass": false, "comment": "退回原因"}
```

通过时 `pass=true`；退回时 `comment` 必填。接口响应后均回读单据：通过必须为 `APPROVED`，退回必须为 `RETURNED`。写请求超时或连接异常不自动重试，只回读状态确认。

### FMSS RPA 配置

`GET /iit/config?version=` 已确认可调用，`version` 可为空。目前没有实测 data schema；客户端只原样返回通用 `data`，不映射为本地 popupRules。

## 本地 Company 与 FMSS 分公司

本地 `companies` 只有 `id`、`name`、`code`、`operator_name`、`notes`、`active`、时间戳字段，没有 FMSS `branchCode`。

- 当前本地 `Company.code`：`17001`、`17020`。
- 实测 FMSS 成都申报机构：`branchCode=19020`。
- 实测的成都申报单行中同时存在机构代码 `17020`，证明本地公司代码可作为 FMSS 申报机构范围内的组织代码，但不是 FMSS 申报机构代码本身。

因此必须增加显式映射，最低字段为：`company_id`、`fmss_branch_code`、`fmss_branch_name`、`active`、创建/更新时间。不要用 `Company.code == branchCode` 直接关联。若后续支持一家公司对应多个 FMSS 申报机构，映射表应设计为一对多。

## 状态与审批语义

申报单状态以 FMSS `document.status` 为准：

- `NOT_SUBMITTED`：仅进度查询使用的虚拟未提交状态。
- `DRAFT`：草稿，可编辑、导入、保存、提交。
- `REVIEWING`：审核中。
- `APPROVED`：当前阶段审核通过。
- `RETURNED`：已退回，可修改、重新导入、重新提交。

不存在独立的“单据双复核完成”状态。双阶段完成的业务含义是同一机构、同一期间的 `PRE=APPROVED` 且 `POST=APPROVED`；两张申报单本身仍各自为 `APPROVED`。

审批记录还使用：`SENDING`、`SEND_FAILED`、`WITHDRAWN`、`FORCE_FINISHED`。实测审批日志中已出现 `REVIEWING`、`WITHDRAWN`、`APPROVED`。

## `canReturn` 与撤回/退回

`canReturn` 是服务端基于阶段联动和状态计算出的“可退回”业务提示，不是当前用户的最终操作权限。

- 提交人撤回：`POST /iit/withdraw/{id}`，仅 `REVIEWING`，由拟稿人或管理员执行，状态回到 `DRAFT`。
- 复核岗退回：`POST /iit/decision`，参数 `{ id, pass: false, comment }`，仅当前复核人或管理员执行，状态到 `RETURNED`。

实测单据 `id=2` 处于 `REVIEWING`，`canReturn=true`，页面“撤回”可用而“退回”禁用。这证明 `canReturn` 不能被解释为“当前人可以退回”，更不是“提交人撤回”开关；客户端需要同时使用服务端权限、当前审核人身份和最终接口校验。

## 复核岗待我审核列表

没有发现文档定义的专用“待我审核”接口。实测可用接口是：

```text
GET /iit/approval-log?branchCode=19020&month=2026-07
```

真实响应为 `{ code, msg, data: { rows, canManage } }`。`rows` 包含 `approvalId`、`declarationId`、`currentApprovalId`、`declarationStatus`、`branchCode`、`taxMonth`、`stage`、`approvalStatus`、`reviewer`、`reviewedAt`、`decisionComment`、`todoStatus`、`canForceFinish` 等字段。

首期“待我审核”列表应由客户端过滤：`approvalStatus === 'REVIEWING' && reviewer === 当前 FMSS 用户名`。点击列表项后用 `GET /iit/review/{declarationId}` 打开单据详情。不要把 `/iit/review/{id}` 当作列表接口。

## 与《个税申报 PC 客户端接口对接文档》比对

附件文档是接口范围说明，不能替代本次 DEV 实测。当前结论如下：

- 已纳入当前增量实现并有真实结构依据：`branches`、`sheets`、`declaration`、`approval-log`、`review/{id}`、`reviewers`、`import`、`submit`、`decision`、`config`。
- 已在浏览器实际验证：PRE/POST declaration 查询、PRE Sheets 返回、PRE 导入成功、POST 导入被前置条件拒绝、审批日志返回结构。
- 已在本地契约测试验证但没有发起真实写入：`submit`、`decision`。本次没有对真实申报单执行提交、通过或退回。
- 附件文档中存在、但当前代码尚未开放的能力：`/iit/draft`、`/iit/progress`、`/iit/progress/export`、`/iit/certificate/*`、`/iit/attachment/*`、`/iit/org-config*`、`/iit/certificate-mapping*`、`/iit/config/rpa` 以及 RPA 规则维护写接口。
- `/iit/withdraw/{id}` 在附件文档中有定义，但当前 TaxWorkbench 不代理、不显示税务岗撤回按钮；`canReturn` 也不转换为撤回动作。
- 附件文档的环境前缀示例不能作为程序推断规则。本次 DEV 实测实际使用 `/fmss/prod-api`，程序继续只读取 `FMSS_LOGIN_URL` 与 `FMSS_API_BASE_URL`。

### 后续实操优先级

1. 先补只读接口实测：`/iit/progress`、`/iit/certificate/{id}`、`/iit/config/rpa`、`/iit/reviewers`，只记录 HTTP/code/data 结构，不写入。
2. 在确认 PRE 进入 `APPROVED` 后，再单独安排 POST 导入实测；当前 POST 失败已证明服务端前置校验有效。
3. `draft`、`certificate` 上传、submit、decision 属于写操作，必须单独确认测试单据、测试文件和回滚边界后再执行。
