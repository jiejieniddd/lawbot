import { Card, List, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
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
            {m.role === 'assistant' ? (
              <div className="md-body" style={{ marginTop: 4 }}>
                <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{m.content}</ReactMarkdown>
              </div>
            ) : (
              <div style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{m.content}</div>
            )}
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
      <style>{`
        .md-body h1, .md-body h2, .md-body h3 {
          margin: 0.7em 0 0.35em;
          font-size: 1.05rem;
          font-weight: 650;
          line-height: 1.35;
        }
        .md-body h1:first-child, .md-body h2:first-child, .md-body h3:first-child {
          margin-top: 0;
        }
        .md-body p { margin: 0.4em 0; line-height: 1.55; }
        .md-body ul, .md-body ol { margin: 0.4em 0; padding-left: 1.35em; }
        .md-body li { margin: 0.2em 0; }
        .md-body blockquote {
          margin: 0.5em 0;
          padding: 0.35em 0.75em;
          border-left: 3px solid #c5d0dc;
          color: #445566;
          background: #f7f9fb;
        }
        .md-body a { color: #1f4e79; }
        .md-body code {
          font-family: ui-monospace, Consolas, monospace;
          font-size: 0.9em;
          padding: 0.1em 0.3em;
          background: #eef2f6;
          border-radius: 3px;
        }
        .md-body pre {
          margin: 0.5em 0;
          padding: 0.6em 0.75em;
          overflow: auto;
          background: #eef2f6;
          border-radius: 6px;
        }
      `}</style>
    </div>
  )
}
