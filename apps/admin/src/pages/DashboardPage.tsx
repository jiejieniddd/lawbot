import { Card, Col, Row, Statistic } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

type Stats = {
  users: number
  end_users: number
  admins: number
  conversations: number
  messages: number
  knowledge_documents: number
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get<Stats>('/api/admin/stats/overview')).data,
  })

  return (
    <div>
      <h2>仪表盘</h2>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={isLoading}>
            <Statistic title="C端用户" value={data?.end_users ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={isLoading}>
            <Statistic title="管理员" value={data?.admins ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={isLoading}>
            <Statistic title="会话" value={data?.conversations ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={isLoading}>
            <Statistic title="消息" value={data?.messages ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={4}>
          <Card loading={isLoading}>
            <Statistic title="知识文档" value={data?.knowledge_documents ?? 0} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
