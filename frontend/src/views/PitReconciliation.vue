<template>
  <div v-loading="pageLoading" class="pit-page">
    <section class="card workflow-card">
      <div class="card-header"><div><strong>个税核对底稿</strong><p>缴款前、缴款后是长期独立保存的真实底稿；重算和人工原因均按阶段隔离。</p><div class="pit-context"><span>公司：{{ companyName }}</span><span>所属期：{{ periodLabel }}</span></div></div><div class="pit-header-actions"><StageTabs v-model="activeStage" :disabled="readOnly" /><el-button v-if="overview?.exists" link type="primary" @click="exportWorkpaper"><el-icon><Download /></el-icon>导出当前阶段</el-button></div></div>
      <div class="card-body pit-toolbar">
        <div class="pit-workflow-status">
          <el-tag :type="workflowStatusMeta.type" effect="light">{{ workflowStatusMeta.label }}</el-tag>
          <span>{{ workflowStatusMeta.description }}</span>
          <el-tag v-if="fmssState !== 'APPROVED'" effect="plain" :type="fmssState === 'REVIEWING' ? 'warning' : 'info'">
            {{ activeStage === 'post_payment' ? '线上状态：' : 'FMSS：' }}{{ fmssStateLabel }}
          </el-tag>
        </div>
        <div class="pit-refresh-time"><small>数据刷新时间</small><strong>{{ dataRefreshedAt || '—' }}</strong></div>
        <div v-if="!readOnly" class="pit-actions">
          <el-tooltip :content="periodId ? '重新获取当前阶段底稿、数据准备和当前核对结果' : '请先选择所属期'">
            <span><el-button :disabled="!periodId" @click="refreshPreparationData">刷新准备数据</el-button></span>
          </el-tooltip>
          <el-button :disabled="!periodId" :loading="fmssRefreshing" @click="refreshFmssState()">刷新线上状态</el-button>
          <el-tooltip :content="recalculateDisabledReason">
            <span><el-button type="primary" :loading="recalculateLoading" :disabled="Boolean(recalculateDisabledReason)" @click="recalculate(activeStage)"><el-icon><RefreshRight /></el-icon>重算</el-button></span>
          </el-tooltip>
          <el-tooltip v-if="activeStage === 'pre_payment'" :content="aggregateButtonTooltip">
            <span><el-dropdown split-button type="warning" :loading="aggregateLoading" :disabled="Boolean(aggregateDisabledReason)" @click="aggregateReasons('refresh_generated')" @command="aggregateReasons"><span>一键汇总原因</span><template #dropdown><el-dropdown-menu><el-dropdown-item command="refresh_generated">更新自动汇总</el-dropdown-item><el-dropdown-item command="fill_empty">仅补空白</el-dropdown-item></el-dropdown-menu></template></el-dropdown></span>
          </el-tooltip>
          <el-tooltip :content="submitDisabledReason">
            <span><el-button type="success" :disabled="Boolean(submitDisabledReason)" @click="openSubmitReviewer">提交审核</el-button></span>
          </el-tooltip>
        </div>
      </div>
    </section>

    <section class="card workflow-card pit-source-panel">
      <div class="card-header"><div class="pit-readiness-heading"><strong>数据准备</strong><el-tag :type="readinessMeta.type" effect="light">{{ readinessMeta.label }}</el-tag><p>{{ readinessSummary }}</p></div><div class="pit-readiness-actions"><el-tooltip content="仅重新获取当前阶段的数据准备情况"><el-button circle :loading="readinessLoading" :disabled="!periodId || readinessLoading" @click="refreshReadiness"><el-icon><RefreshRight /></el-icon></el-button></el-tooltip><el-button link @click="sourcesExpanded = !sourcesExpanded"><el-icon><ArrowUp v-if="sourcesExpanded" /><ArrowDown v-else /></el-icon></el-button></div></div>
      <div v-if="sourcesExpanded" class="card-body pit-source-grid"><div v-for="source in readiness" :key="source.source_type" class="pit-source-card"><div class="source-name">{{ sourceLabels[source.source_type] ?? source.source_type }}</div><strong :class="`source-${source.source_status}`">{{ sourceStatusLabels[source.source_status] ?? source.source_status }}</strong><small>{{ source.row_count ?? 0 }} 条</small><small v-if="source.issues_json?.length" class="source-issue">{{ source.issues_json.map(item => item.message).filter(Boolean).join('；') }}</small></div></div>
    </section>

    <el-alert v-if="overview?.workpaper?.calculation_status === 'stale'" title="核对来源已改变，请重新计算" type="warning" :closable="false" />
    <section v-if="overview?.exists && overview?.workpaper?.calculation_status !== 'stale'" ref="workspaceRef" :class="['card', 'workflow-card', { 'pit-workspace--fullscreen': isFullscreen }]">
      <div class="card-body pit-filter-bar"><div class="pit-filter-controls"><el-select v-model="orgFilter" clearable filterable placeholder="全部机构" class="pit-filter-org" @change="applySearch"><el-option v-for="item in organizationOptions" :key="item" :label="item" :value="item" /></el-select><el-input v-model="keyword" clearable placeholder="搜索机构、姓名、客户、证件、科目或所得项目" class="pit-filter-keyword" @keyup.enter="applySearch" @clear="applySearch" /><el-radio-group v-model="displayMode" @change="applySearch"><el-radio-button label="all">全部</el-radio-button><el-radio-button label="difference">仅差异</el-radio-button><el-radio-button label="missing">仅缺失</el-radio-button></el-radio-group><el-button @click="applySearch">搜索</el-button><el-button @click="resetFilters">重置</el-button></div><div class="pit-workspace-actions"><el-button type="primary" plain @click="toggleFullscreen"><el-icon><Close v-if="isFullscreen" /><FullScreen v-else /></el-icon>{{ isFullscreen ? '退出全屏' : '全屏查看' }}</el-button></div></div>
      <div class="card-body">
        <el-tabs v-model="activeTab" @tab-change="handleTabChange">
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="汇总税额核对" name="summary"><div class="pit-table-wrap"><el-table v-loading="tabLoading.summary" :data="filteredSummaryRows" border stripe show-summary :summary-method="summarySummaryMethod" :height="tableHeight" class="pit-reconciliation-table" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_full_name" label="营业部全称" width="220" fixed="left" /><el-table-column label="税款所属期" width="190"><template #default>{{ taxPeriodLabel }}</template></el-table-column><MoneyColumn label="申报表税额" field="declared_tax_amount" /><MoneyColumn label="科目余额表期末余额税额" field="balance_tax_amount" /><SummaryDifferenceColumn label="申报表与余额表税额差异1" field="difference_1" tab="taxAmount" /><ReasonColumn label="差异原因1" field="difference_1_manual_reason" kind="summary" /><MoneyColumn label="申报表税额（仅正常工资薪金、经纪人、限售股、利息税）" field="scoped_declared_tax_amount" /><MoneyColumn label="工资表、支撑平台税额" field="payroll_business_tax_amount" /><SummaryDifferenceColumn label="申报表与工资表、支撑平台税额差异2" field="difference_2" tab="taxAmount" /><ReasonColumn label="差异原因2" field="difference_2_manual_reason" kind="summary" /><SummaryDifferenceColumn label="当期工资薪金累计应纳税所得额差异3" field="taxable_income_difference" tab="salaryTaxableIncome" /><ReasonColumn label="差异原因3" field="difference_3_manual_reason" kind="summary" /><SummaryDifferenceColumn label="科目余额表经纪人支出当期发生额与经纪人工资应发金额差异6" field="broker_occurrence_difference" tab="occurrence" /><ReasonColumn label="差异原因6" field="difference_6_manual_reason" kind="summary" /><SummaryDifferenceColumn label="部分税种发生额差异7" field="other_income_difference" tab="occurrence" /><ReasonColumn label="差异原因7" field="difference_7_manual_reason" kind="summary" /></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="申报表汇总数" name="declaration"><div class="pit-table-wrap"><el-table v-loading="tabLoading.declaration" :data="filteredDeclarationRows" border stripe :height="tableHeight" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="190" fixed="left" /><el-table-column prop="declaration_type" label="申报类型" width="150" /><el-table-column prop="income_item" label="所得项目" width="240" /><el-table-column prop="person_count" label="填写人次" width="95" align="right" /><MoneyColumn label="收入合计（元）" field="income_amount" /><MoneyColumn label="应补/退税额（元）" field="tax_amount" /></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="个税明细税额核对" name="taxAmount"><div class="pit-table-wrap"><el-table v-loading="tabLoading.taxAmount" :data="filteredTaxRows" border stripe show-summary :summary-method="taxSummaryMethod" :height="tableHeight" class="pit-reconciliation-table" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="190" fixed="left" /><el-table-column prop="subject_code" label="会计科目" width="110" fixed="left" /><el-table-column prop="subject_name" label="描述" width="180" fixed="left" /><MoneyColumn v-for="column in balanceColumns" :key="column.key" :label="column.label" :field="column.key" /><MoneyColumn label="申报表税额" field="declared_tax_amount" /><DifferenceColumn label="本期差异金额8（申报表-余额表贷方）" field="current_difference" /><ReasonColumn label="差异原因8" field="current_manual_reason" kind="tax" /><DifferenceColumn label="累计差异金额9（申报表-余额表期末余额）" field="cumulative_difference" /><ReasonColumn label="差异原因9" field="cumulative_manual_reason" kind="tax" /><MoneyColumn label="工资表、支撑平台税额" field="business_tax_amount" /><MoneyColumn label="申报表税额（仅正常工资薪金、经纪人、限售股、利息税）" field="scoped_declared_tax_amount" /><TaxDifferenceColumn /><ReasonColumn label="差异原因10" field="business_declared_manual_reason" kind="tax" /></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="其他个税发生额核对" name="occurrence"><div class="pit-table-actions"><el-button :loading="occurrenceDescriptionLoading" @click="exportOccurrenceDescriptions">导出说明</el-button><el-button :loading="occurrenceDescriptionLoading" :disabled="!isEditable" @click="occurrenceDescriptionInput?.click()">导入说明</el-button><input ref="occurrenceDescriptionInput" type="file" accept=".xlsx,.xls" hidden @change="importOccurrenceDescriptions" /></div><div class="pit-table-wrap"><el-table v-loading="tabLoading.occurrence" :data="filteredOccurrenceRows" border stripe show-summary :summary-method="occurrenceSummaryMethod" :height="tableHeight" class="pit-reconciliation-table" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="190" fixed="left" /><el-table-column prop="subject_code" label="会计科目" width="110" fixed="left" /><el-table-column prop="subject_name" label="描述" width="180" fixed="left" /><el-table-column prop="income_type" label="对应税种" width="190" /><MoneyColumn v-for="column in occurrenceBalanceColumns" :key="column.key" :label="column.label" :field="column.key" /><MoneyColumn label="经纪人工资表应发" field="broker_payroll_amount" /><DifferenceColumn label="差异金额11（工资表应发-余额表发生额）" field="broker_occurrence_difference" /><ReasonColumn label="差异原因11" field="broker_occurrence_manual_reason" kind="occurrence" /><MoneyColumn label="发生额应申报收入" field="expected_declared_income" /><el-table-column prop="expected_income_description" label="发生额应申报收入说明" width="220" show-overflow-tooltip /><MoneyColumn label="申报表申报收入" field="actual_declared_income" /><DifferenceColumn label="差异金额12（申报表申报收入-应申报收入）" field="declared_income_difference" /><ReasonColumn label="差异原因12" field="declared_income_manual_reason" kind="occurrence" /></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="附A1 工资薪金等个税差异" name="salaryTax"><div class="pit-table-wrap"><el-table v-loading="tabLoading.salaryTax" :data="filteredSalaryTaxRows" border stripe :height="tableHeight" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="170" /><el-table-column label="期间" width="110"><template #default>{{ periodLabel }}</template></el-table-column><el-table-column prop="person_or_customer_name" label="姓名" width="130" /><DetailMoneyColumn label="申报税额" :keys="['declared_tax_amount']" fallback="target_amount" /><DetailMoneyColumn label="工资表税额" :keys="['payroll_tax_amount']" fallback="source_amount" /><DetailDifferenceColumn label="差异金额" /><el-table-column label="差异原因" width="250"><template #default="{ row }"><ReasonCell :reason="row.manual_reason ?? row.auto_reason" @open="openReasonEditor(row, 'manual_reason', 'difference')" /></template></el-table-column><el-table-column label="核对项目" width="105"><template #default="{ row }"><el-button link type="primary" @click="openSalaryDrawer(row)">查看</el-button></template></el-table-column></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="附A2 累计应纳税所得额差异明细" name="salaryTaxableIncome"><div class="pit-table-wrap"><el-table v-loading="tabLoading.salaryTaxableIncome" :data="filteredSalaryTaxableIncomeRows" border stripe :height="tableHeight" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="person_or_customer_name" label="姓名" width="130" /><DetailMoneyColumn label="累计应纳税所得额差异（工资表-申报表）" :keys="['taxable_income_difference']" fallback="difference" /><DetailMoneyColumn label="累计专项扣除差异（工资表-申报表）" :keys="['specific_deduction_difference']" /><DetailMoneyColumn label="累计专项附加扣除差异（含个人养老金）（工资表-申报表）" :keys="['special_additional_deduction_difference']" /><DetailMoneyColumn label="其它差异（工资表-申报表）" :keys="['other_deduction_difference', 'other_difference']" /><el-table-column label="申报表税率" width="105"><template #default="{ row }">{{ detailValue(row, 'declaration_rate') ?? '—' }}</template></el-table-column><DetailMoneyColumn label="应纳税额差异（工资表-申报表）" :keys="['tax_difference']" /><el-table-column label="差异原因" width="250"><template #default="{ row }"><ReasonCell :reason="row.manual_reason ?? row.auto_reason" @open="openReasonEditor(row, 'manual_reason', 'difference')" /></template></el-table-column></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="附A3 客户利息个税差异明细" name="bondInterest"><div class="pit-table-wrap"><el-table v-loading="tabLoading.bondInterest" :data="filteredBondInterestRows" border stripe :height="tableHeight" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="190" /><el-table-column prop="person_or_customer_name" label="客户姓名" width="130" /><el-table-column prop="id_number" label="证件号码" width="180" /><DetailMoneyColumn label="债券利息收入" :keys="['interest_amount']" /><DetailMoneyColumn label="兑息扣税" :keys="['business_tax_amount']" fallback="source_amount" /><DetailMoneyColumn label="申报税额" :keys="['declared_tax_amount']" fallback="target_amount" /><DetailDifferenceColumn label="差异金额" /><el-table-column label="差异原因" width="250"><template #default="{ row }"><ReasonCell :reason="row.manual_reason ?? row.auto_reason" @open="openReasonEditor(row, 'manual_reason', 'difference')" /></template></el-table-column></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'pre_payment'" label="附A4 限售股个税差异明细" name="restrictedStock"><div class="pit-table-wrap"><el-table v-loading="tabLoading.restrictedStock" :data="filteredRestrictedStockRows" border stripe :height="tableHeight" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_name" label="营业部名称" width="190" /><el-table-column prop="person_or_customer_name" label="客户姓名" width="130" /><el-table-column prop="id_number" label="证件号码" width="180" /><el-table-column label="证券名称" width="180"><template #default="{ row }">{{ detailList(row, 'security_names') || '—' }}</template></el-table-column><DetailMoneyColumn label="转让收入额" :keys="['sale_amount']" /><DetailMoneyColumn label="利息税" :keys="['business_tax_amount']" fallback="source_amount" /><DetailMoneyColumn label="申报税额" :keys="['declared_tax_amount']" fallback="target_amount" /><DetailDifferenceColumn label="差异金额" /><el-table-column label="差异原因" width="250"><template #default="{ row }"><ReasonCell :reason="row.manual_reason ?? row.auto_reason" @open="openReasonEditor(row, 'manual_reason', 'difference')" /></template></el-table-column></el-table></div></el-tab-pane>
          <el-tab-pane v-if="activeStage === 'post_payment'" label="缴税核对" name="postPaymentCheck"><div class="pit-table-wrap"><el-table v-loading="tabLoading.postPaymentCheck" :data="filteredSummaryRows" border stripe show-summary :summary-method="postPaymentSummaryMethod" :height="tableHeight" class="pit-reconciliation-table" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column prop="org_code" label="机构代码" width="105" fixed="left" /><el-table-column prop="org_full_name" label="营业部全称" width="220" fixed="left" /><MoneyColumn label="申报表" field="declared_tax_amount" /><MoneyColumn label="完税证明" field="certificate_tax_amount" /><DifferenceColumn label="申报表与完税证明差异金额11" field="difference_4" /><ReasonColumn label="差异原因11" field="difference_4_manual_reason" kind="summary" /><MoneyColumn label="银行流水个税" field="bank_tax_amount" /><DifferenceColumn label="完税证明与银行流水差异金额12" field="difference_5" /><ReasonColumn label="差异原因12" field="difference_5_manual_reason" kind="summary" /></el-table></div></el-tab-pane>
          <el-tab-pane v-for="sheet in rawSheetTabs" :key="sheet.key" :label="sheet.name" :name="sheet.key"><div class="pit-table-wrap"><el-table v-loading="rawSheets[sheet.key].loading" :data="filteredRawRows(sheet.key)" border stripe :height="tableHeight" class="pit-raw-table" :header-cell-class-name="headerCellClassName" :cell-class-name="pitCellClassName"><el-table-column v-for="(column, index) in rawSheets[sheet.key].columns" :key="column.key" :prop="column.key" :label="column.label" :width="rawColumnWidth(column.label)" :fixed="index < 2 ? 'left' : undefined" show-overflow-tooltip><template #default="{ row }"><span :class="column.label.includes('差异') ? differenceClass(row[column.key]) : ''">{{ displayCell(row[column.key]) }}</span></template></el-table-column></el-table></div><el-pagination v-if="rawSheets[sheet.key].total > rawPageSize" class="pit-pagination" background layout="total, prev, pager, next" :page-size="rawPageSize" :total="rawSheets[sheet.key].total" :current-page="rawSheets[sheet.key].page" @current-change="loadRawSheet(sheet.key, $event)" /></el-tab-pane>
        </el-tabs>
      </div>
    </section>
    <ReasonEditorDialog v-model="reasonDialogVisible" :field-label="editingReasonFieldLabel" :reason="editingReasonText" :editable="isEditable" :saving="reasonSaving" @save="saveReason" />
    <el-dialog v-model="reviewerDialogVisible" title="选择FMSS复核人" width="420px"><el-select v-model="selectedReviewer" style="width:100%" placeholder="请选择复核人"><el-option v-for="item in reviewerOptions" :key="item.username" :label="item.label" :value="item.username" /></el-select><template #footer><el-button @click="reviewerDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitOnlineLoading" :disabled="!selectedReviewer" @click="submitOnline">提交审核</el-button></template></el-dialog>
    <el-drawer v-model="detailDrawerVisible" title="工资薪金核对项目" size="560px"><el-table :data="salaryComparisonItems" border size="small"><el-table-column prop="name" label="项目" min-width="150" /><el-table-column label="工资金额" width="110"><template #default="{ row }">{{ formatMoney(row.payroll_amount) }}</template></el-table-column><el-table-column label="申报金额" width="110"><template #default="{ row }">{{ formatMoney(row.declaration_amount) }}</template></el-table-column><el-table-column label="差异金额" width="105"><template #default="{ row }">{{ formatMoney(row.difference) }}</template></el-table-column><el-table-column prop="tax_rate" label="税率" width="75" /><el-table-column label="税额影响" width="105"><template #default="{ row }">{{ formatMoney(row.tax_effect) }}</template></el-table-column></el-table><div v-if="!salaryComparisonItems.length" class="empty-inline">该记录没有可展开的扣除项目。</div></el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElButton, ElMessage, ElMessageBox, ElTableColumn, ElTooltip } from 'element-plus'
import { ArrowDown, ArrowUp, Close, Download, FullScreen, RefreshRight } from '@element-plus/icons-vue'
import { fmssApi, pitReconciliationApi, type PitBankTaxMatch, type PitDeclarationSummary, type PitDifferenceDetail, type PitOccurrenceCheck, type PitOrgSummary, type PitOverviewResponse, type PitReadinessItem, type PitTaxAmountCheck } from '../api'
import StageTabs from '../components/pit/StageTabs.vue'
import ReasonCell from '../components/pit/ReasonCell.vue'
import ReasonEditorDialog from '../components/pit/ReasonEditorDialog.vue'
import type { PaymentStage } from '../features/pit/contracts'

type RawTabKey = 'balanceSheet' | 'bondDetail' | 'restrictedDetail' | 'comprehensiveDeclaration' | 'classifiedDeclaration' | 'restrictedDeclaration' | 'postCertificate' | 'postBankStatement' | 'postBankTaxDetail'
type PitTabKey = 'summary' | 'declaration' | 'taxAmount' | 'occurrence' | 'salaryTax' | 'salaryTaxableIncome' | 'bondInterest' | 'restrictedStock' | 'postPaymentCheck' | RawTabKey
type ReasonKind = 'summary' | 'tax' | 'occurrence' | 'difference'
type ReasonField = 'difference_1_manual_reason' | 'difference_2_manual_reason' | 'difference_3_manual_reason' | 'difference_4_manual_reason' | 'difference_5_manual_reason' | 'difference_6_manual_reason' | 'difference_7_manual_reason' | 'current_manual_reason' | 'cumulative_manual_reason' | 'business_declared_manual_reason' | 'broker_occurrence_manual_reason' | 'declared_income_manual_reason' | 'manual_reason'
type TableRow = Record<string, unknown>
const reasonFieldLabels: Record<ReasonField, string> = { difference_1_manual_reason:'差异原因1', difference_2_manual_reason:'差异原因2', difference_3_manual_reason:'差异原因3', difference_4_manual_reason:'差异原因11', difference_5_manual_reason:'差异原因12', difference_6_manual_reason:'差异原因6', difference_7_manual_reason:'差异原因7', current_manual_reason:'差异原因8', cumulative_manual_reason:'差异原因9', business_declared_manual_reason:'差异原因10', broker_occurrence_manual_reason:'差异原因11', declared_income_manual_reason:'差异原因12', manual_reason:'差异原因' }
const props = defineProps<{ companyId?: number | null; periodId: number | null; periodLabel?: string; companyName?: string; readOnly?: boolean; initialStage?: PaymentStage }>()
const readOnly = computed(() => props.readOnly === true)
const periodLabel = computed(() => props.periodLabel || '未选择')
const taxPeriodLabel = computed(() => { const match=periodLabel.value.match(/(\d{4})\D+(\d{1,2})/); if(!match) return periodLabel.value; const year=Number(match[1]); const month=Number(match[2]); const mm=String(month).padStart(2,'0'); const last=String(new Date(year,month,0).getDate()).padStart(2,'0'); return `${year}.${mm}.01-${year}.${mm}.${last}` })
const companyName = computed(() => props.companyName || '未选择')
const postPaymentReady = computed(() => readiness.value.some((item) => item.source_type === 'tax_certificate' && ['ready', 'ready_empty'].includes(item.source_status)) && readiness.value.some((item) => item.source_type === 'bank_statement' && ['ready', 'ready_empty'].includes(item.source_status)))
const postPaymentPreparationReason = computed(() => {
  if (activeStage.value !== 'post_payment') return ''
  const missing = readiness.value
    .filter((item) => item.source_status === 'missing' || item.source_status === 'invalid' || item.issues_json?.length)
    .map((item) => sourceLabels[item.source_type] ?? item.source_type)
  return missing.length ? `请先完成必要数据准备：${[...new Set(missing)].join('、')}` : ''
})
const postPaymentHint = computed(() => postPaymentReady.value ? '使用完税凭证和银行流水进行扣款后核对' : '请先导入完税凭证和银行流水')
const overview = ref<PitOverviewResponse | null>(null); const readiness = ref<PitReadinessItem[]>([]); const summaryRows = ref<PitOrgSummary[]>([]); const taxAmountRows = ref<PitTaxAmountCheck[]>([]); const occurrenceRows = ref<PitOccurrenceCheck[]>([]); const declarationRows = ref<PitDeclarationSummary[]>([]); const salaryTaxRows = ref<PitDifferenceDetail[]>([]); const salaryTaxableIncomeRows = ref<PitDifferenceDetail[]>([]); const bondInterestRows = ref<PitDifferenceDetail[]>([]); const restrictedStockRows = ref<PitDifferenceDetail[]>([]); const bankMatchRows = ref<PitBankTaxMatch[]>([])
const fmssState = ref('NOT_SUBMITTED'); const doubleReviewCompleted = ref(false); const fmssStateUnavailable = ref(false); const fmssRefreshing = ref(false); const submitOnlineLoading = ref(false); const reviewerDialogVisible = ref(false); const selectedReviewer = ref(''); const reviewerOptions = ref<Array<{ username: string; label: string }>>([])
const preRawSheetTabs: Array<{ key: RawTabKey; name: string }> = [{ key:'balanceSheet',name:'科目余额表' },{ key:'bondDetail',name:'债券利息明细' },{ key:'restrictedDetail',name:'限售股明细' },{ key:'comprehensiveDeclaration',name:'综合所得申报表' },{ key:'classifiedDeclaration',name:'分类所得申报表' },{ key:'restrictedDeclaration',name:'限售股所得申报表' }]
const postRawSheetTabs: Array<{ key: RawTabKey; name: string }> = [{ key:'postCertificate',name:'个税完税凭证' },{ key:'postBankStatement',name:'银行流水' },{ key:'postBankTaxDetail',name:'银行流水个税税额明细' }]
const allRawSheetTabs = [...preRawSheetTabs, ...postRawSheetTabs]
const rawSheetTabs = computed(() => activeStage.value === 'pre_payment' ? preRawSheetTabs : postRawSheetTabs)
const rawSheetName = Object.fromEntries(allRawSheetTabs.map((sheet) => [sheet.key,sheet.name])) as Record<RawTabKey,string>
const pitTabKeys: PitTabKey[] = ['summary','declaration','taxAmount','occurrence','salaryTax','salaryTaxableIncome','bondInterest','restrictedStock','postPaymentCheck',...allRawSheetTabs.map((sheet) => sheet.key)]
const activeTab = ref<PitTabKey>('summary'); const pageLoading = ref(false); const recalculateLoading = ref(false); const aggregateLoading = ref(false); const readinessLoading = ref(false); const occurrenceDescriptionLoading = ref(false); const occurrenceDescriptionInput = ref<HTMLInputElement | null>(null); const dataRefreshedAt = ref(''); const sourcesExpanded = ref(false); const orgFilter = ref(''); const keyword = ref(''); const displayMode = ref<'all' | 'difference' | 'missing'>('all'); const workspaceRef = ref<HTMLElement | null>(null); const tableHeight = ref(620); const isFullscreen = ref(false)
const overviewCache = new Map<string, PitOverviewResponse>()
let requestGeneration = 0
let fmssRequestGeneration = 0
const tabLoading = reactive(Object.fromEntries(pitTabKeys.map((key) => [key,false]))) as Record<PitTabKey,boolean>; const tabLoaded = reactive(Object.fromEntries(pitTabKeys.map((key) => [key,false]))) as Record<PitTabKey,boolean>
const rawPageSize = 100
const rawSheets = reactive(Object.fromEntries(allRawSheetTabs.map((sheet) => [sheet.key,{ columns:[] as Array<{ key:string; label:string }>,rows:[] as TableRow[],total:0,page:1,loading:false }]))) as Record<RawTabKey,{ columns:Array<{ key:string;label:string }>;rows:TableRow[];total:number;page:number;loading:boolean }>
const reasonDialogVisible = ref(false); const reasonSaving = ref(false); const editingReasonRow = ref<TableRow | null>(null); const editingReasonField = ref<ReasonField | null>(null); const editingReasonKind = ref<ReasonKind>('summary'); const editingReasonText = ref(''); const editingReasonFieldLabel = computed(() => editingReasonField.value ? reasonFieldLabels[editingReasonField.value] : '差异原因'); const detailDrawerVisible = ref(false); const detailDrawerRow = ref<PitDifferenceDetail | null>(null)
const sourceLabels: Record<string, string> = { organization_mapping:'机构主数据', salary:'工资薪金', pit_declaration:'实际个税申报', balance_sheet:'科目余额表', broker:'证券经纪人', bond_interest:'债券利息', restricted_stock:'限售股', tax_certificate:'完税证明', bank_statement:'银行流水' }; const sourceStatusLabels: Record<string, string> = { ready:'已就绪', ready_empty:'已就绪（无记录）', missing:'缺失', invalid:'数据异常', not_applicable:'无相关业务' }
const balanceColumns = [{ key:'opening_balance',label:'期初余额' },{ key:'debit_amount',label:'借方金额' },{ key:'credit_amount',label:'贷方金额' },{ key:'closing_balance',label:'期末余额' }]; const occurrenceBalanceColumns = [...balanceColumns,{ key:'occurrence_amount',label:'科目余额表当期发生额' }]
const activeStage = ref<PaymentStage>(props.initialStage || 'pre_payment')
const workflowStatus = computed(() => String(overview.value?.workpaper?.workflow_status || 'data_preparation'))
const fmssStateLabel = computed(() => doubleReviewCompleted.value ? '双复核完成' : ({ NOT_SUBMITTED:'未提交', DRAFT:'线上草稿', REVIEWING:'审核中', APPROVED:'已复核', RETURNED:'已退回' }[fmssState.value] || fmssState.value))
const workflowStatusMeta = computed(() => doubleReviewCompleted.value ? { label:'双复核完成', type:'success' as const, description:'缴款前、缴款后底稿均已通过FMSS复核，当前期间已永久锁定。' } : ({
  data_preparation: { label:'数据准备', type:'warning' as const, description:'来源数据尚未齐全或需要重新计算。当前可修改、重算，也可按需要提交。' },
  pending_submission: { label:'待提交', type:'primary' as const, description:'当前底稿已完成重算，可继续填写差异原因；确认后可以提交。' },
  submitted: { label:'已提交', type:'info' as const, description:'当前版本已提交支撑平台，正在等待复核，底稿已锁定。' },
  returned: { label:'已退回', type:'danger' as const, description:'当前版本已被复核退回，可修改或重新计算；修改后进入待提交。' },
  reviewed: { label:'已复核', type:'success' as const, description:'当前版本已复核通过，底稿已锁定。' },
}[workflowStatus.value] || { label:workflowStatus.value, type:'info' as const, description:'当前底稿状态未知。' }))
const isEditable = computed(() => !readOnly.value && !fmssStateUnavailable.value && ['data_preparation','pending_submission','returned'].includes(workflowStatus.value) && !['REVIEWING','APPROVED'].includes(fmssState.value))
const recalculateDisabledReason = computed(() => {
  if (!props.periodId) return '请先选择所属期'
  if (fmssStateUnavailable.value) return '线上状态无法确认，当前已保守锁定'
  if (workflowStatus.value === 'submitted') return '当前版本已提交，不能重新计算'
  if (workflowStatus.value === 'reviewed') return '当前版本已复核，不能修改'
  if (activeStage.value === 'post_payment' && postPaymentPreparationReason.value) return postPaymentPreparationReason.value
  return ''
})
const submitDisabledReason = computed(() => {
  if (!props.periodId) return '请先选择所属期'
  if (fmssStateUnavailable.value) return '线上状态无法确认，当前已保守锁定'
  if (fmssState.value === 'REVIEWING') return 'FMSS正在审核中'
  if (fmssState.value === 'APPROVED') return 'FMSS已经复核通过'
  return ''
})
const aggregateDisabledReason = computed(() => {
  if (!props.periodId) return '请先选择所属期'
  if (workflowStatus.value === 'submitted') return '当前版本已提交，不能汇总原因'
  if (workflowStatus.value === 'reviewed') return '当前版本已复核，不能汇总原因'
  return ''
})
const aggregateButtonTooltip = computed(() => aggregateDisabledReason.value || '根据下级人工原因更新空白或已有自动汇总内容，不覆盖人工填写内容。')
const organizationOptions = computed(() => [...new Set(summaryRows.value.map((row) => row.org_code).filter(Boolean))])
const readinessMeta = computed(() => {
  const abnormal = readiness.value.some((item) => item.source_status === 'invalid' || !!item.issues_json?.length)
  const missing = readiness.value.some((item) => item.source_status === 'missing')
  return abnormal ? { label:'有异常', type:'danger' as const } : missing ? { label:'待补充', type:'warning' as const } : { label:'已完成', type:'success' as const }
})
const readinessSummary = computed(() => { const normal=readiness.value.filter(item => ['ready','ready_empty','not_applicable'].includes(item.source_status) && !item.issues_json?.length).length; const abnormal=readiness.value.filter(item => item.source_status === 'invalid' || !!item.issues_json?.length).length; const missing=readiness.value.filter(item => item.source_status === 'missing').length; return `正常 ${normal} ｜ 异常 ${abnormal} ｜ 未上传 ${missing} ｜ 共 ${readiness.value.length}` })
const salaryComparisonItems = computed(() => Array.isArray(detailDrawerRow.value?.detail_json?.comparison_items) ? detailDrawerRow.value?.detail_json?.comparison_items as TableRow[] : [])
function formatMoney(value: unknown): string { if (value === null || value === undefined || value === '') return '—'; const numeric = Number(value); return Number.isFinite(numeric) ? numeric.toLocaleString('zh-CN',{ minimumFractionDigits:2,maximumFractionDigits:2 }) : '—' }
function formatDateTime(value: Date) { const pad = (number: number) => String(number).padStart(2, '0'); return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}` }
function isDifference(value: unknown): boolean { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Math.abs(Number(value)) > .01 }
function headerCellClassName({ column }: { column: { label?: string } }) {
  const label = String(column?.label || '')
  if (label.includes('差异')) return 'pit-header-difference'
  if (label.includes('余额') || label.includes('借方') || label.includes('贷方') || label === '会计科目' || label === '描述') return 'pit-header-accounting'
  if (label.includes('工资') || label.includes('业务')) return 'pit-header-payroll'
  if (label.includes('申报') || label.includes('完税')) return 'pit-header-tax'
  if (label.includes('银行')) return 'pit-header-bank'
  if (label.includes('经纪人') || label.includes('其他收入')) return 'pit-header-occurrence'
  return 'pit-header-base'
}
function differenceClass(value: unknown) { return value === null || value === undefined || value === '' ? 'pit-diff pit-diff--missing' : isDifference(value) ? 'pit-diff pit-diff--difference' : 'pit-diff' }
const differenceFields = new Set(['difference_1','difference_2','taxable_income_difference','difference_4','difference_5','broker_occurrence_difference','other_income_difference','current_difference','cumulative_difference','business_declared_difference','declared_income_difference','difference'])
function pitCellClassName({ row, column }: { row: TableRow; column: { property?: string } }) {
  const field = column.property
  if (!field || !differenceFields.has(field)) return ''
  const value = row[field] ?? (row.detail_json as Record<string, unknown> | undefined)?.[field]
  if (value === null || value === undefined || value === '') return 'pit-cell-diff-missing'
  return Number.isFinite(Number(value)) && Math.abs(Number(value)) > 0.01 ? 'pit-cell-diff-alert' : ''
}
function summarizeField(rows: TableRow[], field: string) {
  let total = 0
  let missingCount = 0
  for (const row of rows) {
    const raw = row[field]
    if (raw === null || raw === undefined || raw === '') {
      missingCount += 1
      continue
    }
    const value = Number(raw)
    if (!Number.isFinite(value)) {
      missingCount += 1
      continue
    }
    total += value
  }
  return { total, missingCount }
}
const summarySumFields = new Set(['declared_tax_amount','balance_tax_amount','difference_1','scoped_declared_tax_amount','payroll_business_tax_amount','difference_2','taxable_income_difference','broker_occurrence_difference','other_income_difference'])
const taxSumFields = new Set(['opening_balance','debit_amount','credit_amount','closing_balance','business_tax_amount','declared_tax_amount','current_difference','cumulative_difference','scoped_declared_tax_amount','business_declared_difference'])
const occurrenceSumFields = new Set(['opening_balance','debit_amount','credit_amount','closing_balance','occurrence_amount','broker_payroll_amount','broker_occurrence_difference','expected_declared_income','actual_declared_income','declared_income_difference'])
function tableSummary(fields: Set<string>, { columns, data }: { columns: Array<{ property?: string }>; data: TableRow[] }) {
  return columns.map((column, index) => {
    if (index === 0) return '合计'
    const field = column.property
    if (!field || !fields.has(field)) return ''
    const { total, missingCount } = summarizeField(data, field)
    const nonZeroDifference = differenceFields.has(field) && isDifference(total)
    if (!missingCount && !nonZeroDifference) return formatMoney(total)
    return h('span', {
      class: ['pit-summary-value', nonZeroDifference ? 'pit-summary-diff-alert' : '', missingCount ? 'pit-summary-incomplete' : ''],
      title: missingCount ? `当前合计基于已有有效数据，存在 ${missingCount} 条缺失记录` : undefined,
    }, `${missingCount ? '⚠ ' : ''}${formatMoney(total)}`)
  })
}
function summarySummaryMethod(context: { columns: Array<{ property?: string }>; data: TableRow[] }) { return tableSummary(summarySumFields, context) }
function postPaymentSummaryMethod(context: { columns: Array<{ property?: string }>; data: TableRow[] }) { return tableSummary(new Set(['declared_tax_amount','certificate_tax_amount','difference_4','bank_tax_amount','difference_5']), context) }
function taxSummaryMethod(context: { columns: Array<{ property?: string }>; data: TableRow[] }) { return tableSummary(taxSumFields, context) }
function occurrenceSummaryMethod(context: { columns: Array<{ property?: string }>; data: TableRow[] }) { return tableSummary(occurrenceSumFields, context) }
function detailValue(row: { detail_json?: Record<string, unknown> | null }, ...keys: string[]) { for (const key of keys) { const value = row.detail_json?.[key]; if (value !== null && value !== undefined) return value } return null }
function detailList(row: { detail_json?: Record<string, unknown> | null }, key: string) { const value = row.detail_json?.[key]; return Array.isArray(value) ? value.join('、') : typeof value === 'string' ? value : '' }
function rowVisible(row: TableRow, values: unknown[]) { const text = JSON.stringify(row).toLowerCase(); if (keyword.value && !text.includes(keyword.value.toLowerCase())) return false; const rowOrg = row.org_code ?? row['机构代码']; if (orgFilter.value && rowOrg !== orgFilter.value) return false; if (displayMode.value === 'difference') return values.some(isDifference); if (displayMode.value === 'missing') return values.some((value) => value === null || value === undefined || value === ''); return true }
const filteredSummaryRows = computed(() => summaryRows.value.filter((row) => rowVisible(row as unknown as TableRow, activeStage.value === 'pre_payment' ? [row.difference_1,row.difference_2,row.taxable_income_difference,row.broker_occurrence_difference,row.other_income_difference] : [row.difference_4,row.difference_5]))); const filteredTaxRows = computed(() => taxAmountRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.current_difference,row.cumulative_difference,row.business_declared_difference]))); const filteredOccurrenceRows = computed(() => occurrenceRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.broker_occurrence_difference,row.declared_income_difference]))); const filteredDeclarationRows = computed(() => declarationRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.income_amount,row.tax_amount]))); const filteredSalaryTaxRows = computed(() => salaryTaxRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.difference]))); const filteredSalaryTaxableIncomeRows = computed(() => salaryTaxableIncomeRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.difference]))); const filteredBondInterestRows = computed(() => bondInterestRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.difference]))); const filteredRestrictedStockRows = computed(() => restrictedStockRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.difference]))); const filteredBankMatches = computed(() => bankMatchRows.value.filter((row) => rowVisible(row as unknown as TableRow,[row.debit_amount])))
function isRawTab(tab: PitTabKey): tab is RawTabKey { return allRawSheetTabs.some((sheet) => sheet.key === tab) }
function filteredRawRows(tab: RawTabKey) { return rawSheets[tab].rows.filter((row) => rowVisible(row,Object.entries(row).filter(([key]) => key.includes('差异')).map(([,value]) => value))) }
function displayCell(value: unknown) { return value === null || value === undefined || value === '' ? '—' : String(value) }
function rawColumnWidth(column: string) { return Math.min(280,Math.max(110,column.length * 15 + 32)) }
function visibleTableWrap() { return Array.from(workspaceRef.value?.querySelectorAll<HTMLElement>('.pit-table-wrap') || []).find((element) => element.offsetParent !== null) || null }
function updateTableHeight() { if (typeof window === 'undefined') return; const wrap = visibleTableWrap(); const height = isFullscreen.value && wrap?.clientHeight ? wrap.clientHeight : Math.min(620, Math.max(560, window.innerHeight - 300)); tableHeight.value = Math.max(320, height) }
function scheduleTableHeight() { void nextTick(() => window.requestAnimationFrame(updateTableHeight)) }
function toggleFullscreen() { isFullscreen.value = !isFullscreen.value; if (typeof document !== 'undefined') document.body.style.overflow = isFullscreen.value ? 'hidden' : ''; scheduleTableHeight() }
function scrollTableTo(percent: number) {
  const root = workspaceRef.value
  if (!root) return
  const candidates = Array.from(root.querySelectorAll<HTMLElement>('.pit-table-wrap .el-scrollbar__wrap, .pit-table-wrap .el-table__body-wrapper'))
  const visibleCandidates = candidates.filter((element) => element.offsetParent !== null)
  const scrollElement = (visibleCandidates.length ? visibleCandidates : candidates).find((element) => element.scrollWidth > element.clientWidth + 1) || (visibleCandidates.length ? visibleCandidates : candidates)[0]
  if (!scrollElement) return
  const left = Math.max(0, Math.min(1, percent)) * Math.max(0, scrollElement.scrollWidth - scrollElement.clientWidth)
  scrollElement.scrollTo({ left, behavior: 'smooth' })
}
async function loadRawSheet(tab: RawTabKey,page=1,generation=requestGeneration) { if (!props.periodId) return; const state=rawSheets[tab]; state.loading=true; try { const { data }=await pitReconciliationApi.getSheetData(props.periodId,activeStage.value,rawSheetName[tab],page,rawPageSize,{ keyword:keyword.value || undefined, org_code:orgFilter.value || undefined, display_mode:displayMode.value }); if (generation !== requestGeneration) return; state.columns=data.columns.map((key,index) => ({ key,label:data.column_labels?.[index] || key })); state.rows=data.rows; state.total=data.total; state.page=data.page; tabLoaded[tab]=true } catch(error:any) { if (generation === requestGeneration) ElMessage.error(error?.response?.data?.detail || '原始明细加载失败') } finally { if (generation === requestGeneration) state.loading=false } }
function overviewCacheKey(stage: 'pre_payment' | 'post_payment') { return `${props.companyId ?? 'none'}:${props.periodId}:${stage}` }
async function fetchOverview(stage: 'pre_payment' | 'post_payment', force = false) { if (!props.periodId) return null; const key=overviewCacheKey(stage); if (!force && overviewCache.has(key)) return overviewCache.get(key)!; const response=(await pitReconciliationApi.getOverview(props.periodId,stage)).data; overviewCache.set(key,response); return response }
async function loadOverview(force = false,generation=requestGeneration) { const result = await fetchOverview(activeStage.value,force); if (generation === requestGeneration) overview.value = result }
async function loadReadiness(generation=requestGeneration) { if (!props.periodId) return; const result = (await pitReconciliationApi.getReadiness(props.periodId,activeStage.value)).data; if (generation === requestGeneration) readiness.value = result }
async function refreshReadiness() { if (!props.periodId || readinessLoading.value) return; readinessLoading.value = true; try { await loadReadiness(); ElMessage.success('数据准备情况已刷新') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '数据准备情况刷新失败') } finally { readinessLoading.value = false } }
async function ensureTabLoaded(tab: PitTabKey,generation=requestGeneration) { if (!props.periodId || tabLoaded[tab] || tabLoading[tab]) return; if (isRawTab(tab)) { await loadRawSheet(tab,1,generation); return } tabLoading[tab] = true; try { const periodId = props.periodId; const stage=activeStage.value; let rows: unknown; if (tab === 'summary' || tab === 'postPaymentCheck') rows = (await pitReconciliationApi.getSummary(periodId,stage)).data; if (tab === 'taxAmount') rows = (await pitReconciliationApi.getTaxAmountChecks(periodId,stage)).data; if (tab === 'occurrence') rows = (await pitReconciliationApi.getOccurrenceChecks(periodId,stage)).data; if (tab === 'declaration') rows = (await pitReconciliationApi.getDeclarationSummary(periodId,stage)).data; if (tab === 'salaryTax') rows = (await pitReconciliationApi.getDifferences(periodId,stage,{ detail_type:'salary_tax' })).data; if (tab === 'salaryTaxableIncome') rows = (await pitReconciliationApi.getDifferences(periodId,stage,{ detail_type:'salary_taxable_income' })).data; if (tab === 'bondInterest') rows = (await pitReconciliationApi.getDifferences(periodId,stage,{ detail_type:'bond_interest_tax' })).data; if (tab === 'restrictedStock') rows = (await pitReconciliationApi.getDifferences(periodId,stage,{ detail_type:'restricted_stock_tax' })).data; if (generation !== requestGeneration) return; if (tab === 'summary' || tab === 'postPaymentCheck') summaryRows.value = rows as PitOrgSummary[]; if (tab === 'taxAmount') taxAmountRows.value = rows as PitTaxAmountCheck[]; if (tab === 'occurrence') occurrenceRows.value = rows as PitOccurrenceCheck[]; if (tab === 'declaration') declarationRows.value = rows as PitDeclarationSummary[]; if (tab === 'salaryTax') salaryTaxRows.value = rows as PitDifferenceDetail[]; if (tab === 'salaryTaxableIncome') salaryTaxableIncomeRows.value = rows as PitDifferenceDetail[]; if (tab === 'bondInterest') bondInterestRows.value = rows as PitDifferenceDetail[]; if (tab === 'restrictedStock') restrictedStockRows.value = rows as PitDifferenceDetail[]; tabLoaded[tab] = true } catch (error: any) { if (generation === requestGeneration) ElMessage.error(error?.response?.data?.detail || '核对数据加载失败') } finally { if (generation === requestGeneration) tabLoading[tab] = false } }
function markDataRefreshed(generation: number) { if (generation === requestGeneration) dataRefreshedAt.value = formatDateTime(new Date()) }
async function initializePage(generation=requestGeneration) {
  if (!props.periodId) return
  pageLoading.value = true
  try {
    await Promise.all([loadOverview(false,generation), loadReadiness(generation)])
    if (generation !== requestGeneration || !overview.value?.exists) return

    // Every PRE/POST switch synchronizes the online declaration before this stage is displayed.
    await refreshFmssState(true, false)
    if (generation !== requestGeneration) return
    await loadOverview(true,generation)
    await ensureTabLoaded(activeTab.value,generation)
    if (tabLoaded[activeTab.value]) markDataRefreshed(generation)
    scheduleTableHeight()
  } catch {
    if (generation === requestGeneration) ElMessage.error('个税底稿初始化失败')
  } finally {
    if (generation === requestGeneration) pageLoading.value = false
  }
}
async function handleTabChange(value: string | number) { await ensureTabLoaded(value as PitTabKey,requestGeneration); scheduleTableHeight() }
function resetPitPage() { overview.value = null; readiness.value = []; dataRefreshedAt.value = ''; fmssState.value = 'NOT_SUBMITTED'; doubleReviewCompleted.value = false; fmssStateUnavailable.value = false; summaryRows.value = []; taxAmountRows.value = []; occurrenceRows.value = []; declarationRows.value = []; salaryTaxRows.value = []; salaryTaxableIncomeRows.value = []; bondInterestRows.value = []; restrictedStockRows.value = []; bankMatchRows.value = []; orgFilter.value = ''; keyword.value = ''; displayMode.value = 'all'; isFullscreen.value = false; if (typeof document !== 'undefined') document.body.style.overflow = ''; updateTableHeight(); pitTabKeys.forEach((key) => { tabLoaded[key] = false; tabLoading[key] = false; if (isRawTab(key)) Object.assign(rawSheets[key],{ columns:[],rows:[],total:0,page:1,loading:false }) }) }
async function refreshPreparationData() { if (!props.periodId) return; const generation = ++requestGeneration; overviewCache.delete(overviewCacheKey(activeStage.value)); tabLoaded[activeTab.value] = false; try { await Promise.all([loadOverview(true,generation), loadReadiness(generation)]); await ensureTabLoaded(activeTab.value,generation); if (tabLoaded[activeTab.value]) markDataRefreshed(generation); ElMessage.success('当前阶段数据准备已刷新') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '当前阶段数据准备刷新失败') } }
function workflowStatusFromFmss(status: string) { return ({ REVIEWING:'submitted', APPROVED:'reviewed', RETURNED:'returned' } as Record<string, string>)[status] }
function applyFmssState(status: string, declarationId?: string | null, doubleReviewed = false) {
  fmssState.value = status
  doubleReviewCompleted.value = doubleReviewed
  fmssStateUnavailable.value = false
  if (!overview.value) return
  const workflowStatus = workflowStatusFromFmss(status)
  const nextOverview = {
    ...overview.value,
    workpaper: {
      ...overview.value.workpaper,
      ...(workflowStatus ? { workflow_status: workflowStatus } : {}),
      ...(declarationId ? { platform_submission_id: declarationId } : {}),
    },
  }
  overview.value = nextOverview
  overviewCache.set(overviewCacheKey(activeStage.value), nextOverview)
}
async function refreshFmssState(silent = false, reloadOverview = true) {
  if (!props.periodId) return false
  const pageGeneration = requestGeneration
  const stage = activeStage.value
  const fmssGeneration = ++fmssRequestGeneration
  fmssRefreshing.value = true
  try {
    // This endpoint synchronizes the local workflow state on the server. Keep the loaded workpaper rows intact.
    const { data } = await fmssApi.declaration(props.periodId, stage)
    if (fmssGeneration !== fmssRequestGeneration || pageGeneration !== requestGeneration || stage !== activeStage.value) return false
    applyFmssState(data.status, data.declaration_id, Boolean(data.double_review_completed))
    if (reloadOverview) await loadOverview(true, pageGeneration)
    if (!silent) ElMessage.success('FMSS线上状态已刷新')
    return true
  } catch (error: any) {
    if (fmssGeneration === fmssRequestGeneration && overview.value?.workpaper?.platform_submission_id) fmssStateUnavailable.value = true
    if (!silent && fmssGeneration === fmssRequestGeneration && pageGeneration === requestGeneration) ElMessage.error('线上状态刷新失败')
    return false
  } finally {
    if (fmssGeneration === fmssRequestGeneration) fmssRefreshing.value = false
  }
}
function localWorkpaperReady() { const workpaper = overview.value?.workpaper; return workpaper?.calculation_status === 'success' && ['ready', 'complete'].includes(String(workpaper?.data_status || '')) }
async function openSubmitReviewer() {
  if (!props.periodId || submitDisabledReason.value) return
  try {
    const { data } = await fmssApi.reviewers(props.periodId, activeStage.value)
    const rows = Array.isArray(data) ? data : data?.rows || []
    reviewerOptions.value = rows.map((row: any) => { const username = String(row?.username || row?.userName || row?.loginName || row?.account || row || '').trim(); return { username, label: String(row?.name || row?.displayName || username) } }).filter((row: { username: string }) => row.username)
    if (reviewerOptions.value.length === 1) selectedReviewer.value = reviewerOptions.value[0].username
    reviewerDialogVisible.value = true
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || 'FMSS复核人列表获取失败')
  }
}
async function submitOnline() { if (!props.periodId || !selectedReviewer.value || submitOnlineLoading.value) return; submitOnlineLoading.value = true; try { await fmssApi.submit(props.periodId, selectedReviewer.value, activeStage.value); reviewerDialogVisible.value = false; const refreshed = await refreshFmssState(); if (!refreshed) { fmssStateUnavailable.value = true; return } if (activeStage.value === 'post_payment' && fmssState.value !== 'REVIEWING') { ElMessage.error(`FMSS提交接口已响应，但线上状态为${fmssStateLabel.value}`); return } ElMessage.success('FMSS提交审核已完成') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || 'FMSS提交审核失败') } finally { submitOnlineLoading.value = false } }
async function applySearch() { if (isRawTab(activeTab.value)) { tabLoaded[activeTab.value] = false; await loadRawSheet(activeTab.value,1,requestGeneration) } }
async function resetFilters() { orgFilter.value=''; keyword.value=''; displayMode.value='all'; await applySearch() }
async function recalculate(stage: 'pre_payment' | 'post_payment') { if (!props.periodId || !isEditable.value) return; recalculateLoading.value = true; try { await pitReconciliationApi.recalculate(props.periodId, stage); overviewCache.delete(overviewCacheKey(stage)); resetPitPage(); await initializePage(); ElMessage.success(stage === 'pre_payment' ? '缴款前底稿已重新计算' : '缴款后底稿已重新计算') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '计算失败') } finally { recalculateLoading.value = false } }
async function aggregateReasons(mode: 'fill_empty' | 'refresh_generated') {
  if (!props.periodId || aggregateDisabledReason.value || aggregateLoading.value) return
  try {
    await ElMessageBox.confirm('系统将重新汇总明细原因。空白及已有自动汇总内容会更新，人工填写内容不会被覆盖。是否继续？', '一键汇总原因', { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' })
  } catch { return }
  aggregateLoading.value = true
  try {
    const { data } = await pitReconciliationApi.aggregateReasons(props.periodId, activeStage.value, mode)
    const generation = ++requestGeneration
    overviewCache.delete(overviewCacheKey(activeStage.value))
    ;(['summary', 'taxAmount', 'occurrence', 'salaryTax', 'salaryTaxableIncome', 'bondInterest', 'restrictedStock'] as PitTabKey[]).forEach((tab) => { tabLoaded[tab] = false })
    await Promise.all([loadOverview(true, generation), loadReadiness(generation)])
    await ensureTabLoaded(activeTab.value, generation)
    if (data.changed) ElMessage.success(data.message + '，当前修订版 v' + data.draft_revision)
    else ElMessage.info(data.message)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '汇总原因失败')
  } finally {
    aggregateLoading.value = false
  }
}
function exportWorkpaper() { if (props.periodId) window.open(pitReconciliationApi.exportUrl(props.periodId,activeStage.value), '_blank') }
function downloadBlob(blob: Blob, filename: string) { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.style.display = 'none'; document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 0) }
async function exportOccurrenceDescriptions() { if (!props.periodId || occurrenceDescriptionLoading.value) return; occurrenceDescriptionLoading.value = true; try { const { data } = await pitReconciliationApi.exportOccurrenceDescriptions(props.periodId, activeStage.value); downloadBlob(data, `其他个税发生额核对说明_${props.periodLabel || props.periodId}.xlsx`); ElMessage.success('说明表已导出') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '说明表导出失败') } finally { occurrenceDescriptionLoading.value = false } }
async function importOccurrenceDescriptions(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''; if (!file || !props.periodId || !isEditable.value || occurrenceDescriptionLoading.value) return; occurrenceDescriptionLoading.value = true; try { const { data } = await pitReconciliationApi.importOccurrenceDescriptions(props.periodId, activeStage.value, file); if (data.updated_count) { const generation = ++requestGeneration; overviewCache.delete(overviewCacheKey(activeStage.value)); tabLoaded.occurrence = false; await Promise.all([loadOverview(true, generation), ensureTabLoaded('occurrence', generation)]); ElMessage.success(`已更新 ${data.updated_count} 条发生额应申报收入说明`) } else { ElMessage.info(data.unmatched_count ? `没有可更新的说明，${data.unmatched_count} 条未匹配` : '没有可更新的说明') } } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '说明导入失败') } finally { occurrenceDescriptionLoading.value = false } }
function openReasonEditor(row: TableRow, field: ReasonField, kind: ReasonKind) { editingReasonRow.value = row; editingReasonField.value = field; editingReasonKind.value = kind; editingReasonText.value = String(row[field] ?? row.auto_reason ?? ''); reasonDialogVisible.value = true }
async function saveReason(reason: string) { const row = editingReasonRow.value; const field = editingReasonField.value; if (!isEditable.value || !row || !field || !props.periodId) return; reasonSaving.value = true; try { const payload = { [field]: reason }; if (editingReasonKind.value === 'summary') await pitReconciliationApi.updateSummary(props.periodId,activeStage.value,Number(row.id),payload as any); if (editingReasonKind.value === 'tax') await pitReconciliationApi.updateTaxAmountCheck(props.periodId,activeStage.value,Number(row.id),payload as any); if (editingReasonKind.value === 'occurrence') await pitReconciliationApi.updateOccurrenceCheck(props.periodId,activeStage.value,Number(row.id),payload as any); if (editingReasonKind.value === 'difference') await pitReconciliationApi.updateDifference(props.periodId,activeStage.value,Number(row.id),{ manual_reason:reason }); overviewCache.delete(overviewCacheKey(activeStage.value)); await loadOverview(true); row[field] = reason; editingReasonText.value = reason; reasonDialogVisible.value = false; ElMessage.success('人工原因已保存') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '保存失败') } finally { reasonSaving.value = false } }
async function drillDown(tab: PitTabKey, orgCode?: string) { orgFilter.value = orgCode || ''; activeTab.value = tab; await ensureTabLoaded(tab) }; function openSalaryDrawer(row: unknown) { detailDrawerRow.value = row as PitDifferenceDetail; detailDrawerVisible.value = true }; function subjectDetailTab(row: PitTaxAmountCheck): PitTabKey { return row.subject_code === '21510008' ? 'bondInterest' : row.subject_code === '21510009' ? 'restrictedStock' : 'salaryTax' }
watch([() => props.companyId, () => props.periodId, () => props.initialStage, activeStage],async () => { if (props.initialStage && activeStage.value !== props.initialStage) activeStage.value = props.initialStage; const generation = ++requestGeneration; activeTab.value = activeStage.value === 'pre_payment' ? 'summary' : 'postPaymentCheck'; resetPitPage(); await initializePage(generation) },{ immediate:true })
onMounted(() => { updateTableHeight(); window.addEventListener('resize', updateTableHeight) })
onBeforeUnmount(() => { window.removeEventListener('resize', updateTableHeight); if (typeof document !== 'undefined') document.body.style.overflow = '' })
const MoneyColumn = defineComponent({ props:{ label:{ type:String,required:true },field:{ type:String,required:true } },setup(componentProps) { return () => h(ElTableColumn,{ prop:componentProps.field,label:componentProps.label,width:Math.max(140,rawColumnWidth(componentProps.label)),align:'right' },{ default:({ row }: { row:TableRow }) => formatMoney(row[componentProps.field]) }) } })
const DifferenceColumn = defineComponent({ props:{ label:{ type:String,required:true },field:{ type:String,required:true } },setup(componentProps) { return () => h(ElTableColumn,{ prop:componentProps.field,label:componentProps.label,width:140,align:'right' },{ default:({ row}: { row:TableRow }) => h('span',{ class:differenceClass(row[componentProps.field]) },formatMoney(row[componentProps.field])) }) } })
const SummaryDifferenceColumn = defineComponent({ props:{ label:{ type:String,required:true },field:{ type:String,required:true },tab:{ type:String,required:true } },setup(componentProps) { return () => h(ElTableColumn,{ prop:componentProps.field,label:componentProps.label,width:rawColumnWidth(componentProps.label),align:'right' },{ default:({ row }: { row:PitOrgSummary }) => h('button',{ class:['pit-diff-link',differenceClass((row as unknown as TableRow)[componentProps.field])],onClick:() => drillDown(componentProps.tab as PitTabKey,row.org_code) },formatMoney((row as unknown as TableRow)[componentProps.field])) }) } })
const TaxDifferenceColumn = defineComponent({ setup() { return () => h(ElTableColumn,{ prop:'business_declared_difference',label:'差异10',width:125,align:'right' },{ default:({ row }: { row:PitTaxAmountCheck }) => h('button',{ class:['pit-diff-link',differenceClass(row.business_declared_difference)],onClick:() => drillDown(subjectDetailTab(row),row.org_code) },formatMoney(row.business_declared_difference)) }) } })
const ReasonColumn = defineComponent({ props:{ label:{ type:String,default:'差异原因' },field:{ type:String,required:true },kind:{ type:String,required:true } },setup(componentProps) { return () => h(ElTableColumn,{ label:componentProps.label,width:250 },{ default:({ row }: { row:TableRow }) => h(ReasonCell,{ reason:row[componentProps.field] ?? row.auto_reason, onOpen:() => openReasonEditor(row,componentProps.field as ReasonField,componentProps.kind as ReasonKind) }) }) } })
const DetailMoneyColumn = defineComponent({ props:{ label:{ type:String,required:true },keys:{ type:Array,required:true },fallback:{ type:String,default:'' } },setup(componentProps) { return () => h(ElTableColumn,{ prop:(componentProps.keys as string[])[0] || componentProps.fallback || undefined,label:componentProps.label,width:125,align:'right' },{ default:({ row }: { row:PitDifferenceDetail }) => formatMoney(detailValue(row,...(componentProps.keys as string[])) ?? (componentProps.fallback ? (row as unknown as TableRow)[componentProps.fallback] : null)) }) } })
const DetailDifferenceColumn = defineComponent({ props:{ label:{ type:String,required:true } },setup(componentProps) { return () => h(ElTableColumn,{ prop:'difference',label:componentProps.label,width:125,align:'right' },{ default:({ row }: { row:PitDifferenceDetail }) => h('span',{ class:differenceClass(row.difference) },formatMoney(row.difference)) }) } })
</script>

<style scoped>
.pit-page { display:grid; gap:16px; }.card-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }.pit-header-actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:flex-end; }.card-header p { margin:6px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.pit-context { display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:10px; color:var(--el-text-color-secondary); font-size:12px; }.pit-toolbar,.pit-filter-bar { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }.pit-workflow-status { display:flex; align-items:center; gap:8px; flex:1 1 340px; color:var(--el-text-color-secondary); font-size:13px; }.pit-refresh-time { min-width:155px; }.pit-actions { display:flex; gap:8px; flex-wrap:wrap; }.pit-toolbar small { display:block; color:var(--el-text-color-secondary); margin-bottom:3px; }.pit-readiness-heading { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }.pit-readiness-heading p { width:100%; }.pit-readiness-actions { display:flex; align-items:center; gap:4px; }.pit-source-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:10px; }.pit-source-card { display:grid; gap:5px; min-width:0; padding:11px; border:1px solid var(--el-border-color-lighter); border-radius:6px; }.source-name { font-weight:600; }.source-ref { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.source-ready,.source-ready_empty,.source-not_applicable { color:var(--el-color-success); }.source-missing,.source-invalid { color:var(--el-color-danger); }.source-issue { color:var(--el-color-warning); cursor:help; font-size:12px; }.pit-filter-org { width:180px; }.pit-filter-keyword { width:min(320px,100%); }.pit-table-wrap { width:100%; min-width:0; max-width:100%; overflow:hidden; }.pit-subtitle { margin:16px 0 8px; font-weight:600; }.pit-diff { font-variant-numeric:tabular-nums; }.pit-diff--difference { color:var(--el-color-danger); font-weight:600; }.pit-diff--ok { color:var(--el-color-success); font-weight:600; }.pit-diff--missing { color:var(--el-color-warning); font-weight:600; }.pit-diff-link { border:0; background:transparent; padding:0; font:inherit; cursor:pointer; }.empty-inline { padding:16px 0; color:var(--el-text-color-secondary); } @media (max-width:720px) { .pit-filter-org,.pit-filter-keyword { width:100%; } .pit-actions { width:100%; } .pit-header-actions { width:100%; justify-content:flex-start; } }
.pit-page { width:100%; min-width:0; max-width:100%; }
.pit-page > .card { min-width:0; max-width:100%; }
.pit-page .card-header > div,.pit-toolbar > div { min-width:0; }
.pit-reconciliation-table :deep(.el-table__footer-wrapper .cell) { white-space:nowrap; word-break:keep-all; overflow:visible; font-variant-numeric:tabular-nums; font-weight:600; text-align:right; }
.pit-reconciliation-table :deep(.el-table__footer-wrapper td:first-child .cell) { text-align:left; }
.pit-summary-value { white-space:nowrap; display:inline-block; font-variant-numeric:tabular-nums; }
.pit-table-actions { display:flex; justify-content:flex-end; gap:8px; margin:0 0 8px; }
.pit-source-grid { width:100%; min-width:0; grid-template-columns:repeat(auto-fit,minmax(min(155px,100%),1fr)); }
.pit-toolbar { width:100%; }
.pit-actions { margin-left:auto; }
.pit-filter-controls,.pit-workspace-actions,.pit-column-jumps { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.pit-filter-controls { min-width:0; flex:1 1 auto; }
.pit-workspace-actions { margin-left:auto; justify-content:flex-end; }
.pit-column-jumps { gap:2px; }
.pit-table-wrap { width:100%; min-width:0; max-width:100%; overflow:hidden; }
.pit-table-wrap :deep(.el-table) { width:100% !important; min-width:0; }
.pit-table-wrap :deep(.el-scrollbar__wrap) { overflow-x:auto; }
.pit-table-wrap :deep(.el-scrollbar__bar.is-horizontal) { height:14px; bottom:2px; }
.pit-table-wrap :deep(.el-scrollbar__bar.is-horizontal .el-scrollbar__thumb) { min-width:72px; cursor:ew-resize; }
.pit-table-wrap :deep(.el-table__body-wrapper) { scrollbar-width:auto; }
.pit-table-wrap :deep(.el-table__body-wrapper::-webkit-scrollbar) { height:14px; }
.pit-table-wrap :deep(.el-table__body-wrapper::-webkit-scrollbar-thumb) { background:var(--el-border-color); border-radius:7px; }
.pit-table-wrap :deep(.el-table__fixed-right) { box-shadow:-2px 0 8px rgba(16,24,40,.12); }
.pit-table-wrap :deep(.el-table__header-wrapper th) { background:#f3f4f6; color:#344054; }
.pit-table-wrap :deep(.el-table__header-wrapper th:nth-child(-n+4)) { background:#e8f1fb; color:#1d4e89; }
.pit-table-wrap :deep(.el-table__header-wrapper th:nth-child(n+5):nth-child(-n+10)) { background:#eaf7ef; color:#176b3a; }
.pit-table-wrap :deep(.el-table__header-wrapper th:nth-child(n+11):nth-child(-n+15)) { background:#fff4db; color:#8a5a00; }
.pit-table-wrap :deep(.el-table__header-wrapper th:last-child) { background:#fde8e8; color:#b42318; }
.pit-table-wrap :deep(th.pit-header-base) { background:#f3f4f6; color:#344054; }
.pit-table-wrap :deep(th.pit-header-accounting) { background:#e8f1fb; color:#1d4e89; }
.pit-table-wrap :deep(th.pit-header-payroll) { background:#eaf7ef; color:#176b3a; }
.pit-table-wrap :deep(th.pit-header-tax) { background:#fff4db; color:#8a5a00; }
.pit-table-wrap :deep(th.pit-header-bank) { background:#e8f7f7; color:#146b6b; }
.pit-table-wrap :deep(th.pit-header-occurrence) { background:#f2ebfb; color:#65419a; }
.pit-table-wrap :deep(th.pit-header-difference) { background:#fde8e8; color:#b42318; }
.pit-reconciliation-table :deep(.el-table__footer-wrapper td) { font-weight:700; background:#f5f7fa; border-top:2px solid var(--el-border-color); }
.pit-reconciliation-table :deep(.el-table__footer-wrapper td:has(.pit-summary-incomplete)) { background:#fffbe6; }
.pit-summary-incomplete { color:#ad6800; font-weight:700; cursor:help; }
.pit-summary-diff-alert { color:#cf1322; font-weight:700; }
.pit-reconciliation-table :deep(td.pit-cell-diff-alert) { background:#fff1f0 !important; }
.pit-reconciliation-table :deep(td.pit-cell-diff-alert .cell) { color:#cf1322; font-weight:700; }
.pit-reconciliation-table :deep(td.pit-cell-diff-missing) { background:#fffbe6 !important; }
.pit-reconciliation-table :deep(td.pit-cell-diff-missing .cell) { color:#ad6800; font-weight:600; }
@media (max-width:1180px) { .pit-workspace-actions { width:100%; margin-left:0; justify-content:flex-start; } }
.pit-workspace--fullscreen { position:fixed; inset:8px; z-index:3000; display:flex; flex-direction:column; width:auto; height:calc(100vh - 16px); padding:12px; overflow:hidden; background:var(--el-bg-color); border-radius:8px; box-shadow:0 12px 40px rgba(16,24,40,.2); }
.pit-workspace--fullscreen > .card-body:last-child { min-height:0; flex:1; overflow:hidden; display:flex; flex-direction:column; }
.pit-workspace--fullscreen :deep(.el-tabs) { height:100%; display:flex; flex-direction:column; min-height:0; }
.pit-workspace--fullscreen :deep(.el-tabs__content) { min-height:0; flex:1; display:flex; flex-direction:column; }
.pit-workspace--fullscreen :deep(.el-tab-pane) { height:100%; flex:1; min-height:0; display:flex; flex-direction:column; }
.pit-workspace--fullscreen .pit-table-wrap { height:auto; flex:1; min-height:0; }
@media (max-width:1180px) { .pit-actions { width:100%; margin-left:0; } }
</style>
