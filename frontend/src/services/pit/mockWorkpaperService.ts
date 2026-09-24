import type { LocalWorkpaperContext, LocalWorkpaperPreview, WorkpaperService } from '../../features/pit/contracts'
import { mockDelay } from './mockData'
import { editMockWorkpaper, getMockWorkpaper, recalculateMockWorkpaper, submitMockWorkpaper } from './mockWorkpaperState'

export class MockWorkpaperService implements WorkpaperService {
  async getPreview(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview> { await mockDelay(signal); return getMockWorkpaper(context) }
  async recalculate(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview> { await mockDelay(signal, 700); return recalculateMockWorkpaper(context) }
  async editDraft(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview> { await mockDelay(signal, 250); return editMockWorkpaper(context) }
  async submit(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview> { await mockDelay(signal, 600); return submitMockWorkpaper(context) }
}
