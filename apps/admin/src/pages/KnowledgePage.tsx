import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'

type Doc = {
  id: string
  title: string
  doc_type: string
  status: string
  summary: string | null
  source_uri: string | null
  updated_at?: string | null
  created_at?: string | null
}

type DocForm = {
  title: string
  doc_type: string
  status: string
  summary?: string
  source_uri?: string
}

type ImportJob = {
  id: string
  status: string
  source: string
  config: Record<string, unknown>
  stats: Record<string, unknown>
  error: string | null
  created_at?: string | null
  updated_at?: string | null
}

type Citation = {
  law_name: string
  article_no: string
  text: string
  source_id: string
  category?: string | null
  effective_date?: string | null
}

function DocumentsTab() {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Doc | null>(null)
  const [form] = Form.useForm<DocForm>()
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['knowledge'],
    queryFn: async () => (await api.get<Doc[]>('/api/admin/knowledge/documents')).data,
  })

  const create = useMutation({
    mutationFn: async (values: DocForm) => api.post('/api/admin/knowledge/documents', values),
    onSuccess: () => {
      message.success('已创建')
      closeModal()
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
    onError: () => message.error('创建失败'),
  })

  const update = useMutation({
    mutationFn: async ({ id, values }: { id: string; values: DocForm }) =>
      api.patch(`/api/admin/knowledge/documents/${id}`, values),
    onSuccess: () => {
      message.success('已更新')
      closeModal()
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
    onError: () => message.error('更新失败'),
  })

  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/admin/knowledge/documents/${id}`),
    onSuccess: () => {
      message.success('已删除')
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
    onError: () => message.error('删除失败'),
  })

  function closeModal() {
    setOpen(false)
    setEditing(null)
    form.resetFields()
  }

  function openCreate() {
    setEditing(null)
    form.setFieldsValue({ doc_type: 'law', status: 'draft', title: '', summary: '', source_uri: '' })
    setOpen(true)
  }

  function openEdit(row: Doc) {
    setEditing(row)
    form.setFieldsValue({
      title: row.title,
      doc_type: row.doc_type,
      status: row.status,
      summary: row.summary || '',
      source_uri: row.source_uri || '',
    })
    setOpen(true)
  }

  function onFinish(values: DocForm) {
    if (editing) update.mutate({ id: editing.id, values })
    else create.mutate(values)
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={openCreate}>
          新建文档
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={data}
        columns={[
          { title: '标题', dataIndex: 'title' },
          { title: '类型', dataIndex: 'doc_type' },
          { title: '状态', dataIndex: 'status' },
          { title: '摘要', dataIndex: 'summary', ellipsis: true },
          {
            title: '更新时间',
            dataIndex: 'updated_at',
            render: (v: string | null | undefined) =>
              v ? new Date(v).toLocaleString() : '—',
          },
          {
            title: '操作',
            render: (_, row) => (
              <Space>
                <Button size="small" onClick={() => openEdit(row)}>
                  编辑
                </Button>
                <Button danger size="small" onClick={() => remove.mutate(row.id)}>
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? '编辑知识文档' : '新建知识文档'}
        open={open}
        onCancel={closeModal}
        onOk={() => form.submit()}
        confirmLoading={create.isPending || update.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="doc_type" label="类型">
            <Select
              options={[
                { value: 'law', label: 'law' },
                { value: 'regulation', label: 'regulation' },
                { value: 'faq', label: 'faq' },
              ]}
            />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: 'draft', label: 'draft' },
                { value: 'published', label: 'published' },
                { value: 'archived', label: 'archived' },
              ]}
            />
          </Form.Item>
          <Form.Item name="summary" label="摘要">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="source_uri" label="来源 URI">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function ImportJobsTab() {
  const [maxRows, setMaxRows] = useState<number | null>(500)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['knowledge-import-jobs'],
    queryFn: async () =>
      (await api.get<ImportJob[]>('/api/admin/knowledge-import-jobs')).data,
    refetchInterval: (query) => {
      const rows = query.state.data
      if (!rows?.length) return false
      const busy = rows.some((j) => j.status === 'pending' || j.status === 'running')
      return busy ? 3000 : false
    },
  })

  const createJob = useMutation({
    mutationFn: async () => {
      const body: { config?: { max_rows: number } } = {}
      if (maxRows != null) body.config = { max_rows: maxRows }
      return api.post('/api/admin/knowledge-import-jobs', body)
    },
    onSuccess: () => {
      message.success('已创建导入任务')
      qc.invalidateQueries({ queryKey: ['knowledge-import-jobs'] })
    },
    onError: () => message.error('创建导入任务失败'),
  })

  const statusColor = (s: string) => {
    if (s === 'succeeded') return 'success'
    if (s === 'failed') return 'error'
    if (s === 'running') return 'processing'
    return 'default'
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <span>max_rows</span>
        <InputNumber
          min={0}
          value={maxRows ?? undefined}
          onChange={(v) => setMaxRows(v)}
          placeholder="0=不截断"
        />
        <Button type="primary" loading={createJob.isPending} onClick={() => createJob.mutate()}>
          触发导入
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={data}
        columns={[
          {
            title: '状态',
            dataIndex: 'status',
            width: 110,
            render: (s: string) => <Tag color={statusColor(s)}>{s}</Tag>,
          },
          { title: 'Source', dataIndex: 'source', ellipsis: true },
          {
            title: 'Stats',
            dataIndex: 'stats',
            render: (stats: Record<string, unknown>) => (
              <code style={{ fontSize: 12 }}>{JSON.stringify(stats || {})}</code>
            ),
          },
          {
            title: 'Error',
            dataIndex: 'error',
            ellipsis: true,
            render: (v: string | null) => v || '—',
          },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            render: (v: string | null | undefined) =>
              v ? new Date(v).toLocaleString() : '—',
          },
          {
            title: '更新时间',
            dataIndex: 'updated_at',
            render: (v: string | null | undefined) =>
              v ? new Date(v).toLocaleString() : '—',
          },
        ]}
      />
    </div>
  )
}

function SearchTab() {
  const [q, setQ] = useState('')
  const [topK, setTopK] = useState(5)
  const [submitted, setSubmitted] = useState<{ q: string; top_k: number } | null>(null)

  const { data, isFetching } = useQuery({
    queryKey: ['knowledge-search', submitted],
    enabled: !!submitted?.q,
    queryFn: async () => {
      const res = await api.get<{ query: string; results: Citation[] }>(
        '/api/admin/knowledge/search',
        { params: { q: submitted!.q, top_k: submitted!.top_k } },
      )
      return res.data
    },
  })

  function onSearch() {
    const query = q.trim()
    if (!query) {
      message.warning('请输入检索词')
      return
    }
    setSubmitted({ q: query, top_k: topK })
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          style={{ width: 320 }}
          value={q}
          placeholder="试检索法规条文…"
          onChange={(e) => setQ(e.target.value)}
          onPressEnter={onSearch}
        />
        <InputNumber min={1} max={20} value={topK} onChange={(v) => setTopK(v ?? 5)} />
        <Button type="primary" loading={isFetching} onClick={onSearch}>
          检索
        </Button>
      </Space>
      <Table
        rowKey={(r) => r.source_id}
        loading={isFetching}
        dataSource={data?.results || []}
        columns={[
          { title: '法律名称', dataIndex: 'law_name', width: 180 },
          { title: '条款', dataIndex: 'article_no', width: 100 },
          { title: '正文', dataIndex: 'text', ellipsis: true },
          { title: 'source_id', dataIndex: 'source_id', width: 140 },
          { title: '类别', dataIndex: 'category', width: 100, render: (v) => v || '—' },
        ]}
      />
    </div>
  )
}

export default function KnowledgePage() {
  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Knowledge</h2>
      <Tabs
        items={[
          { key: 'docs', label: '文档', children: <DocumentsTab /> },
          { key: 'jobs', label: '导入任务', children: <ImportJobsTab /> },
          { key: 'search', label: '试检索', children: <SearchTab /> },
        ]}
      />
    </div>
  )
}
