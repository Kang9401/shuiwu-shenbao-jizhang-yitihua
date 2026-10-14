import assert from 'node:assert/strict'
import { build } from 'esbuild'

const calls = []
const api = {
  downloadAll: async (id) => { calls.push(['zip', id]); return { data: new Blob(['zip']) } },
  saveAll: async (id, path) => { calls.push(['save', id, path]); return { data: { saved_count: 2, directory: path } } },
}
globalThis.downloadTest = { api, messages: [] }
const timers = []
globalThis.window = { setTimeout: (fn, delay) => timers.push({ fn, delay }) }
globalThis.document = {
  createElement: () => ({ style: {}, click() { calls.push(['click', this.download]) }, remove() {} }),
  body: { appendChild() {} },
}
const result = await build({
  entryPoints: ['src/services/desktopDownload.ts'], bundle: true, write: false, format: 'esm', platform: 'node',
  plugins: [{ name: 'download-test-api', setup(build) {
    build.onResolve({ filter: /^(\.\.\/api|element-plus)$/ }, args => ({ path: args.path, namespace: 'test' }))
    build.onLoad({ filter: /.*/, namespace: 'test' }, args => ({ contents: args.path === 'element-plus'
      ? 'export const ElMessage = { success: message => globalThis.downloadTest.messages.push(message) }'
      : 'export const workflowApi = globalThis.downloadTest.api' }))
  } }],
})
const { downloadJobArtifacts } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].contents).toString('base64')}`)

await downloadJobArtifacts(1)
assert.deepEqual(calls, [['zip', 1], ['click', '个税申报文件.zip']])
assert.equal(timers[0].delay, 60000)

calls.length = 0
window.pywebview = { api: { choose_directory: async () => ({ path: 'D:/申报' }) } }
await downloadJobArtifacts(2)
assert.deepEqual(calls, [['save', 2, 'D:/申报']])

calls.length = 0
api.saveAll = async () => { throw { response: { status: 403, data: { detail: '仅桌面版允许保存文件到本机目录' } } } }
await downloadJobArtifacts(3)
assert.deepEqual(calls, [['zip', 3], ['click', '个税申报文件.zip']])

calls.length = 0
window.pywebview.api.choose_directory = async () => ({ path: '' })
await downloadJobArtifacts(4)
assert.equal(calls.length, 0, '取消选目录不应下载')

window.pywebview.api.choose_directory = async () => ({ path: 'D:/申报' })
api.saveAll = async () => { throw { response: { status: 403, data: { detail: '其他权限错误' } } } }
await assert.rejects(downloadJobArtifacts(5))
assert.equal(calls.length, 0, '其他权限错误不应被回退掩盖')

delete window.pywebview
api.downloadAll = async () => { throw { response: { status: 404 } } }
await assert.rejects(downloadJobArtifacts(6))
console.log('Download checks passed: browser, desktop, runtime fallback, cancellation and errors')
