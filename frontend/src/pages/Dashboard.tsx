import { BarChart3 } from 'lucide-react';

/**
 * 数据看板：**存量画像**，用于内部大屏与一对一客户演示。
 *
 * 旧版这里是一张按账号的人员活跃度表——那是管理视角，和看板名字不符，
 * 残值（负责对象数、最近活跃）已并入账号管理页，取数端点一并删除。
 *
 * 本版是空壳：确定的内容只有省级中国地图与行业分布两块，等 ECharts 与
 * 自然资源部标准底图接入后填充。刻意不放顶部数字条，也不出现任何标的
 * 与买家名称——演示场景下这些是敏感信息。
 */
export default function Dashboard() {
  return (
    <div className="mx-auto max-w-2xl py-16 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-gray-100">
        <BarChart3 className="h-6 w-6 text-gray-400" />
      </div>
      <h1 className="mb-2 text-lg font-semibold text-gray-900">数据看板建设中</h1>
      <p className="mb-6 text-sm text-gray-500">本版将包含以下两块内容：</p>
      <ul className="mx-auto max-w-xs space-y-2 text-left text-sm text-gray-600">
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-gray-300" />
          标的省级分布地图
        </li>
        <li className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-gray-300" />
          一级行业分布
        </li>
      </ul>
    </div>
  );
}
