<template>
  <div class="workflow-page">
    <section class="card workflow-card">
      <div class="card-header"><div><strong>{{ workflow.name }}</strong><p>{{ workflow.description }}</p></div><span class="tag tag-info">{{ workflow.domain }}</span></div>
      <div class="card-body">
        <div class="workflow-stepbar"><span class="tag tag-success">1 上传收入资料</span><span class="tag" :class="job ? 'tag-success' : 'tag-info'">2 人员核对</span><span class="tag" :class="metrics.can_generate ? 'tag-success' : 'tag-info'">3 补录复核</span><span class="tag" :class="metrics.finalized ? 'tag-success' : 'tag-info'">4 生成申报</span></div>
        <p class="action-hint">复用工资薪金的人员主数据和核对流程。本月收入资料中未出现的在职人员自动列为离职；零收入记录仍视为本月有记录。</p>
        <div class="upload-item workflow-upload-item" :class="{ 'has-file': incomeFiles.length }">
          <label>{{ workflow.code === 'broker_tax' ? '经纪人工资单' : workflow.code === 'intern_tax' ? '实习生工资单' : '劳务报酬工资单' }}</label><input type="file" multiple accept=".xls,.xlsx,.xlsb" :disabled="busy" @change="pickIncome" />
          <span class="upload-status" :class="incomeFiles.length ? 'ready' : 'empty'">{{ incomeFiles.map(f => f.name).join('、') || '请选择工资单文件' }}</span>
          <button class="btn btn-xs btn-ghost" :disabled="!incomeFiles.length" @click="incomeFiles=[]">清除</button>
          <a v-if="templateUrl" class="btn btn-outline" :href="templateUrl" target="_blank">下载导入模板</a>
          <button class="btn btn-primary btn-lg" :disabled="busy || !periodId || !incomeFiles.length" @click="run('initial')">首轮核对</button>
        </div>
      </div>
    </section>
    <section v-if="job" class="card workflow-card">
      <div class="card-header"><strong>核对结果</strong><span>{{ metrics.finalized ? '申报文件已生成' : metrics.can_generate ? '核对通过，可以生成' : '需要补充或修正' }}</span></div>
      <div class="card-body">
        <p>收入记录 {{ metrics.payroll_count || 0 }} 人；新增 {{ metrics.new_count || 0 }} 人；离职 {{ metrics.leaver_count || 0 }} 人。</p>
        <el-alert v-if="job.error_message" :title="job.error_message" type="error" :closable="false" />
        <el-table v-if="issues.length" :data="issues" border><el-table-column prop="message" label="核对问题" /></el-table>
        <div class="action-bar monthly-actions">
          <a v-for="file in reviewFiles" :key="file.id" class="btn btn-outline" :href="workflowApi.artifactDownloadUrl(file.id)" target="_blank">下载人员信息变更表</a>
          <label class="btn btn-outline">上传补录后的变更表<input type="file" accept=".xlsx,.xls" :disabled="busy" @change="pickChanges" /></label>
          <span>{{ changeFile?.name }}</span>
          <button class="btn btn-outline" :disabled="busy || !periodId" @click="run('recheck')">重新核对</button>
          <button class="btn btn-primary" :disabled="busy || !periodId || !metrics.can_generate || !!changeFile" @click="run('generate')">生成申报文件</button>
        </div>
        <p>黄色单元格需要补录。已填写的数据会保留；上传后请重新核对。更换收入资料后须重新进行首轮核对。</p>
        <div v-if="metrics.finalized" class="download-grid">
          <a v-for="file in declarationFiles" :key="file.id" class="download-item" :href="workflowApi.artifactDownloadUrl(file.id)">{{ file.file_name }}</a>
          <a class="btn btn-primary" :href="workflowApi.batchDownloadUrl(job.id)">批量下载申报文件</a>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { workflowApi, type Workflow, type Job } from '../api'
const props = defineProps<{workflow: Workflow; periodId:number|null}>()
const incomeFiles = ref<File[]>([])
const changeFile = ref<File|null>(null)
const job = ref<Job|null>(null)
const busy = ref(false)
let revision = 0
const metrics = computed(() => job.value?.result_summary || {})
const issues = computed(() => Array.isArray(metrics.value.issue_details) ? metrics.value.issue_details : [])
const role = computed(() => ({broker_tax:'broker_income',intern_tax:'intern_salary',part_time_tax:'payroll'}[props.workflow.code] || 'payroll'))
const templateUrl = computed(() => props.workflow.code === 'intern_tax' ? workflowApi.internTemplateUrl() : props.workflow.code === 'part_time_tax' ? workflowApi.partTimeTemplateUrl() : '')
const reviewFiles = computed(() => (job.value?.artifacts || []).filter(f => f.artifact_type === 'personnel_change_review'))
const declarationFiles = computed(() => (job.value?.artifacts || []).filter(f => ['declaration','personnel_collection'].includes(f.artifact_type)))
function pickIncome(event: Event) { incomeFiles.value = Array.from((event.target as HTMLInputElement).files || []); job.value=null; changeFile.value=null }
function pickChanges(event: Event) { changeFile.value=(event.target as HTMLInputElement).files?.[0] || null }
watch(() => [props.workflow.code,props.periodId], async () => {
  const token = ++revision
  incomeFiles.value=[]; changeFile.value=null; job.value=null
  if (!props.periodId) return
  try { const {data} = await workflowApi.latestJob(props.workflow.code,props.periodId); if (token===revision) job.value=data } catch (e:any) { if (e?.response?.status!==404) ElMessage.error('读取上次核对结果失败') }
}, {immediate:true})
async function run(operation: 'initial'|'recheck'|'generate') {
  if (!props.periodId || busy.value) return
  busy.value=true
  const period=props.periodId, code=props.workflow.code, token=revision
  try {
    const ids:number[]=[]
    if (operation==='initial') for (const file of incomeFiles.value) ids.push((await workflowApi.uploadFile(file,role.value,period)).data.id)
    if (operation==='recheck' && changeFile.value) ids.push((await workflowApi.uploadFile(changeFile.value,'personnel_changes',period)).data.id)
    const {data}=await workflowApi.createJob(code,ids,period,operation)
    if (token!==revision) return
    job.value=data; changeFile.value=null
    if (data.status==='failed') ElMessage.error(data.error_message || '处理失败')
    else ElMessage[data.status==='needs_review'?'warning':'success'](data.status==='needs_review'?'请查看并处理核对问题':operation==='generate'?'申报文件已生成':'核对完成')
  } catch(e:any) { ElMessage.error(e?.response?.data?.detail || '处理失败') } finally { busy.value=false }
}
</script>
