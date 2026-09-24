import type { LocalWorkpaperContext, LocalWorkpaperPreview, WorkpaperService } from '../../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../../features/pit/contracts'
import { MockWorkpaperService } from './mockWorkpaperService'

class UnavailableWorkpaperService implements WorkpaperService {
  async getPreview(_context: LocalWorkpaperContext): Promise<LocalWorkpaperPreview> { throw new PitServiceNotIntegratedError() }
  async recalculate(_context: LocalWorkpaperContext): Promise<LocalWorkpaperPreview> { throw new PitServiceNotIntegratedError() }
  async editDraft(_context: LocalWorkpaperContext): Promise<LocalWorkpaperPreview> { throw new PitServiceNotIntegratedError() }
  async submit(_context: LocalWorkpaperContext): Promise<LocalWorkpaperPreview> { throw new PitServiceNotIntegratedError() }
}

export const workpaperService: WorkpaperService = import.meta.env.DEV ? new MockWorkpaperService() : new UnavailableWorkpaperService()
