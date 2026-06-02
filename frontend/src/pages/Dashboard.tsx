import { BarChart3 } from 'lucide-react';

export default function Dashboard() {
  return (
    <div className="max-w-2xl mx-auto py-16 text-center">
      <div className="w-12 h-12 bg-gray-100 flex items-center justify-center mx-auto mb-4">
        <BarChart3 className="w-6 h-6 text-gray-400" />
      </div>
      <h1 className="text-lg font-semibold text-gray-900 mb-2">数据看板建设中</h1>
      <p className="text-sm text-gray-500 mb-6">后续将包含以下功能：</p>
      <ul className="text-sm text-gray-600 space-y-2 text-left max-w-xs mx-auto">
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          标的地域分布
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          一级行业分布
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          行业 Top 10
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          估值 Top 10
        </li>
        <li className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 bg-gray-300 rounded-full shrink-0" />
          活跃买家意向统计
        </li>
      </ul>
    </div>
  );
}
