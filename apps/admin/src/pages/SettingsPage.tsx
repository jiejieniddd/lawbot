import { Card, Descriptions } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function SettingsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => (await api.get<Record<string, unknown>>('/api/admin/settings')).data,
  })

  return (
    <Card title="系统设置（脱敏）" loading={isLoading}>
      <Descriptions column={1} bordered size="small">
        {data &&
          Object.entries(data).map(([k, v]) => (
            <Descriptions.Item key={k} label={k}>
              {Array.isArray(v) ? v.join(', ') : String(v)}
            </Descriptions.Item>
          ))}
      </Descriptions>
    </Card>
  )
}
