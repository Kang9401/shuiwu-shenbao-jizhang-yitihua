import { ElMessage } from 'element-plus'
import { workflowApi } from '../api'

type DesktopApi = { choose_directory?: (initialPath?: string) => Promise<{ path?: string }> }

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function downloadJobArtifacts(jobId: number, suggestedName = '个税申报文件.zip'): Promise<void> {
  const desktopApi = (window as unknown as { pywebview?: { api?: DesktopApi } }).pywebview?.api
  if (desktopApi?.choose_directory) {
    const result = await desktopApi.choose_directory()
    if (!result?.path) return
    const { data } = await workflowApi.saveAll(jobId, result.path)
    ElMessage.success('已保存 ' + data.saved_count + ' 个文件到：' + data.directory)
    return
  }
  const { data } = await workflowApi.downloadAll(jobId)
  downloadBlob(data, suggestedName)
  ElMessage.success('申报文件已开始下载')
}
