import { Settings as SettingsIcon } from 'lucide-react';

export default function Settings() {
  return (
    <div className="max-w-2xl mx-auto py-16 text-center">
      <div className="w-12 h-12 bg-gray-100 flex items-center justify-center mx-auto mb-4">
        <SettingsIcon className="w-6 h-6 text-gray-400" />
      </div>
      <h1 className="text-lg font-semibold text-gray-900 mb-2">设置建设中</h1>
      <p className="text-sm text-gray-500 mb-6">后续将包含以下功能：</p>
      <ul className="text-sm text-gray-600 space-y-2 text-left max-w-xs mx-auto">
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          模型与提示词配置
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          Debug Mode 配置
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          用户与权限
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          字典维护
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          部门 / 项目空间配置
        </li>
      </ul>
    </div>
  );
}
