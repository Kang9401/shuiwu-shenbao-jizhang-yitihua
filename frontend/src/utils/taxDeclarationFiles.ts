export type TaxDeclarationFileRole =
  | 'personnel_collection'
  | 'reconciliation_report'
  | 'working_sheet'
  | 'updated_staff'
  | 'deduction_files'
  | 'staff_change'
  | 'retirement_welfare'
  | 'broker_salary'
  | 'headquarters_salary'
  | 'rank_salary'
  | 'marketing_salary'
  | 'advisor_salary'
  | 'branch_salary'
  | 'digital_ops_salary'
  | 'salary_role_conflict'
  | ''

export interface ClassifiedTaxDeclarationFiles {
  roles: Record<string, File>
  knownArtifacts: File[]
  deductionFiles: File[]
  duplicateWarnings: string[]
}

export function fileIdentity(file: File): string {
  return `${file.name}-${file.size}-${file.lastModified}`
}

export function mergeUniqueFiles(current: File[], incoming: File[]): File[] {
  const merged = new Map(current.map((file) => [fileIdentity(file), file]))
  incoming.forEach((file) => merged.set(fileIdentity(file), file))
  return Array.from(merged.values())
}

export function normalizeFileText(file: File): string {
  const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
  return `${relativePath}/${file.name}`.toLowerCase().replace(/\s+/g, '')
}

export function compactFileText(text: string): string {
  return text.replace(/[_\-—–·.（）()【】\[\]{}、，,：:;；/\\]/g, '')
}

export function detectFileRole(text: string): TaxDeclarationFileRole {
  const compact = compactFileText(text)
  if (compact.includes('人员信息采集员工') || compact.includes('人员信息采集表')) return 'personnel_collection'
  if (compact.includes('核对报告')) return 'reconciliation_report'
  if (compact.includes('平台底稿') || compact.includes('核对底稿') || compact.includes('底稿xlsx')) return 'working_sheet'
  if (compact.includes('当月人员信息表') || compact.includes('更新后人员信息表')) return 'updated_staff'
  if (compact.includes('专项附加扣除') || compact.includes('专项扣除')) return 'deduction_files'
  if (compact.includes('人员信息变动表雇员') || compact.includes('变动表雇员')) return 'staff_change'
  if (compact.includes('退休')) return 'retirement_welfare'
  if (compact.includes('经纪人') || compact.includes('证券经纪')) return 'broker_salary'
  if (compact.includes('总部')) return 'headquarters_salary'
  const rankByName = compact.includes('5位') || compact.includes('五位')
  const marketingByName = compact.includes('7位') || compact.includes('七位')
  if (rankByName && marketingByName) return 'salary_role_conflict'
  if (rankByName) return 'rank_salary'
  if (marketingByName) return 'marketing_salary'
  if (compact.includes('投资顾问') || compact.includes('理财经理') || compact.includes('投顾')) return 'advisor_salary'
  if (compact.includes('机构业务人员') || compact.includes('机构工资')) return 'branch_salary'
  if (compact.includes('数字化运营')) return 'digital_ops_salary'
  if (compact.includes('营销人员') || compact.includes('营销工资')) return 'marketing_salary'
  if (compact.includes('工资横表') || compact.includes('职级工资') || compact.includes('薪资')) return 'rank_salary'
  return ''
}

export function classifyFolderFiles(fileList: File[]): ClassifiedTaxDeclarationFiles {
  const roles: Record<string, File> = {}
  const knownArtifacts: File[] = []
  const deductionFiles: File[] = []
  const duplicateWarnings: string[] = []

  for (const file of fileList) {
    const role = detectFileRole(normalizeFileText(file))
    if (role === 'salary_role_conflict') throw new Error(`文件名同时包含5位和7位标记，无法判断工资类型：${file.name}`)
    if (role === 'deduction_files') deductionFiles.push(file)
    else if (role === 'personnel_collection' || role === 'updated_staff' || role === 'working_sheet' || role === 'reconciliation_report') knownArtifacts.push(file)
    else if (role) {
      const normalizedRole = ['branch_salary', 'digital_ops_salary', 'advisor_salary'].includes(role) ? 'marketing_salary' : role
      if (roles[normalizedRole]) {
        duplicateWarnings.push(`${normalizedRole === 'rank_salary' ? '职级' : normalizedRole === 'marketing_salary' ? '营销' : normalizedRole === 'headquarters_salary' ? '总部' : normalizedRole}：${roles[normalizedRole].name}、${file.name}`)
        continue
      }
      roles[normalizedRole] = file
    }
  }

  return { roles, knownArtifacts, deductionFiles, duplicateWarnings }
}
