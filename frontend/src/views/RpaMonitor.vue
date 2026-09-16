<template>
  <main class="monitor-page">
    <header>
      <div><strong>RPA 任务监控</strong><small>{{ companyName }} · {{ status?.current_run.declaration_month || status?.current_run.month || '未启动' }}</small></div>
      <el-button :icon="Refresh" circle title="刷新" :loading="loading" @click="refresh" />
    </header>
    <section class="run-summary">
      <span>任务</span><strong>{{ status?.current_run.display_name || '暂无任务' }}</strong>
      <span>机构</span><strong>{{ status?.current_run.current_org_code || '-' }} {{ status?.current_run.current_org_name || '' }}</strong>
      <span>状态</span><strong :class="`is-${status?.current_run.status || 'idle'}`">{{ status?.current_run.status || 'idle' }}</strong>
    </section>
    <section class="result-wrap">
      <el-table :data="status?.results || []" size="small" max-height="210">
        <el-table-column prop="code" label="机构" width="90" />
        <el-table-column prop="name" label="名称" min-width="130" />
        <el-table-column label="综合" width="90"><template #default="scope">{{ label(scope.row.comprehensive_income_report) }}</template></el-table-column>
        <el-table-column label="分类" width="90"><template #default="scope">{{ label(scope.row.classified_income_report) }}</template></el-table-column>
        <el-table-column label="限售股" width="90"><template #default="scope">{{ label(scope.row.restricted_stock_report) }}</template></el-table-column>
      </el-table>
    </section>
    <pre ref="logBox" class="monitor-log">{{ logText }}</pre>
    <footer><el-button type="danger" :disabled="!canStop" :loading="status?.current_run.status === 'stopping'" @click="stop">停止任务</el-button></footer>
  </main>
</template>

<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { useRpaMonitor } from '../composables/useRpaMonitor'
import { companyApi, currentCompanyId } from '../api'
const { status, logText, logBox, loading, canStop, refresh, stop } = useRpaMonitor()
const companyName = ref('当前分公司')
onMounted(async () => {
  const id = currentCompanyId()
  if (!id) return
  try { companyName.value = (await companyApi.list()).data.find((item) => item.id === id)?.name || companyName.value } catch {}
})
function label(value: any) { return value?.label || value || '待处理' }
</script>

<style scoped>
.monitor-page{min-width:380px;min-height:420px;height:100vh;box-sizing:border-box;display:grid;grid-template-rows:auto auto auto minmax(160px,1fr) auto;gap:10px;padding:12px;background:#f5f7fa;color:#1d2939}.monitor-page header{display:flex;align-items:center;justify-content:space-between}.monitor-page header div{display:flex;flex-direction:column}.monitor-page header strong{font-size:17px}.monitor-page header small{color:#667085}.run-summary{display:grid;grid-template-columns:52px minmax(0,1fr);gap:6px 10px;padding:10px;background:white;border:1px solid #e4e7ed;border-radius:6px}.run-summary span{color:#667085}.result-wrap{overflow-x:auto;background:white;border:1px solid #e4e7ed}.monitor-log{min-height:160px;margin:0;padding:10px;overflow:auto;white-space:pre-wrap;background:#111827;color:#d1fae5;border-radius:4px;font:12px/1.55 Consolas,monospace}.monitor-page footer{display:flex;justify-content:flex-end}.is-running,.is-starting,.is-stopping{color:#2563eb}.is-succeeded{color:#15803d}.is-failed,.is-cancelled{color:#b42318}
</style>
