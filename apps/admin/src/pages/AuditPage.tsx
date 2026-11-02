import { Card, List, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'

type Conversation = { id: string; title: string; user_id: string; status: string }
type Message = {
  id: string
  role: string
  content: string
  citations: Array<{ law_name: string; article_no: string; text: string; source_id: string }>
}

export default function AuditPage() {
  const [selected, setSelected] = useState<string | null>(null)
  const { data: conversations, isLoading } = useQuery({
    queryKey: ['admin-conversations'],
    queryFn: async () => (await api.get<Conversation[]>('/api/admin/conversations')).data,
  })
  const { data: messages } = useQuery({
    queryKey: ['admin-messages', selected],
    enabled: !!selected,
    queryFn: async () =>
      (await api.get<Message[]>(`/api/admin/conversations/${selected}/messages`)).data,
  })

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 16 }}>
      <Card title="会话审计" loading={isLoading}>
        <List
          dataSource={conversations}
          renderItem={(item) => (
            <List.Item
              style={{
                cursor: 'pointer',
                background: selected === item.id ? '#e6f0fa' : undefined,
              }}
              onClick={() => setSelected(item.id)}
            >
              <List.Item.Meta title={item.title} description={`user: ${item.user_id}`} />
            </List.Item>
          )}
        />
      </Card>
      <Card title="消息与引用">
        {!selected && <Typography.Text type="secondary">选择左侧会话</Typography.Text>}
        {messages?.map((m) => (
          <div key={m.id} style={{ marginBottom: 16 }}>
            <Typography.Text strong>{m.role}</Typography.Text>
            <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{m.content}</div>
            {m.citations?.map((c) => (
              <Card key={c.source_id} size="small" style={{ marginTop: 8, background: '#fff8e8' }}>
                <strong>
                  {c.law_name} {c.article_no}
                </strong>
                <div>{c.text}</div>
              </Card>
            ))}
          </div>
        ))}
      </Card>
    </div>
  )
}
