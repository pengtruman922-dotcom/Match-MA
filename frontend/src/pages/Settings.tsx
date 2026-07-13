import { Settings as SettingsIcon } from 'lucide-react';

export default function Settings() {
  return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center bg-gray-100">
        <SettingsIcon className="h-6 w-6 text-gray-400" />
      </div>
      <h1 className="mb-2 text-lg font-semibold text-gray-900">设置建设中</h1>
      <p className="mb-6 text-sm text-gray-500">后续将逐步沉淀这些管理能力：</p>
      <ul className="mx-auto max-w-xs space-y-2 text-left text-sm text-gray-600">
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 bg-gray-300" />
          模型与提示词配置
        </li>
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 bg-gray-300" />
          后台任务与异常策略
        </li>
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 bg-gray-300" />
          用户与权限
        </li>
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 bg-gray-300" />
          字典维护
        </li>
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 bg-gray-300" />
          部门 / 项目空间配置
        </li>
      </ul>
    </div>
  );
}
