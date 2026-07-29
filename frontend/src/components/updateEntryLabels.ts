import type { BusinessUpdateProcessingScope } from '../types/api';

const UPDATE_SCOPE_LABELS: Record<BusinessUpdateProcessingScope, string> = {
  basic_info: '更新基本信息',
  follow_up: '记录跟进',
  both: '基本信息和跟进都更新',
};

export function updateScopeLabel(scope: BusinessUpdateProcessingScope): string {
  return UPDATE_SCOPE_LABELS[scope] || '录入';
}
