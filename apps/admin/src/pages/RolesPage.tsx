import { useMemo, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Collapse,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

type RoleOut = {
  id: string
  code: string
  name: string
  description: string | null
  is_system: boolean
  enabled: boolean
  permission_codes: string[]
}

type PermissionOut = {
  id: string
  code: string
  name: string
  module: string
  description?: string | null
}

type RoleForm = {
  code: string
  name: string
  description?: string
  enabled: boolean
}

export default function RolesPage() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [permOpen, setPermOpen] = useState(false)
  const [editing, setEditing] = useState<RoleOut | null>(null)
  const [permRole, setPermRole] = useState<RoleOut | null>(null)
  const [checked, setChecked] = useState<string[]>([])
  const [form] = Form.useForm<RoleForm>()

  const { data: roles = [], isLoading } = useQuery({
    queryKey: ['admin-roles'],
    queryFn: async () => (await api.get<RoleOut[]>('/api/admin/roles')).data,
  })

  const { data: permissionsByModule = {} } = useQuery({
    queryKey: ['admin-permissions'],
    queryFn: async () =>
      (await api.get<Record<string, PermissionOut[]>>('/api/admin/permissions')).data,
  })

  const createMut = useMutation({
    mutationFn: async (values: RoleForm) => api.post('/api/admin/roles', values),
    onSuccess: async () => {
      message.success('角色已创建')
      setOpen(false)
      await qc.invalidateQueries({ queryKey: ['admin-roles'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '创建失败'),
  })

  const patchMut = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: Partial<RoleForm> }) =>
      api.patch(`/api/admin/roles/${id}`, body),
    onSuccess: async () => {
      message.success('角色已更新')
      setOpen(false)
      await qc.invalidateQueries({ queryKey: ['admin-roles'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '更新失败'),
  })

  const deleteMut = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/admin/roles/${id}`),
    onSuccess: async () => {
      message.success('已删除')
      await qc.invalidateQueries({ queryKey: ['admin-roles'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '删除失败'),
  })

  const permMut = useMutation({
    mutationFn: async ({ id, permission_codes }: { id: string; permission_codes: string[] }) =>
      api.put(`/api/admin/roles/${id}/permissions`, { permission_codes }),
    onSuccess: async () => {
      message.success('权限已保存')
      setPermOpen(false)
      await qc.invalidateQueries({ queryKey: ['admin-roles'] })
      await qc.invalidateQueries({ queryKey: ['admin-me'] })
    },
    onError: (e: any) => message.error(e?.response?.data?.detail || '保存失败'),
  })

  const moduleItems = useMemo(
    () =>
      Object.entries(permissionsByModule).map(([module, perms]) => ({
        key: module,
        label: module,
        children: (
          <Checkbox.Group
            style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            value={checked}
            onChange={(vals) => {
              const other = checked.filter((c) => !perms.some((p) => p.code === c))
              setChecked([...other, ...(vals as string[])])
            }}
            options={perms.map((p) => ({
              label: `${p.name}（${p.code}）`,
              value: p.code,
            }))}
          />
        ),
      })),
    [permissionsByModule, checked],
  )

  function openCreate() {
    setEditing(null)
    form.setFieldsValue({ code: '', name: '', description: '', enabled: true })
    setOpen(true)
  }

  function openEdit(row: RoleOut) {
    setEditing(row)
    form.setFieldsValue({
      code: row.code,
      name: row.name,
      description: row.description || '',
      enabled: row.enabled,
    })
    setOpen(true)
  }

  function openPerms(row: RoleOut) {
    setPermRole(row)
    setChecked(row.permission_codes || [])
    setPermOpen(true)
  }

  return (
    <Card
      title="角色管理"
      extra={
        <Button type="primary" onClick={openCreate}>
          新建角色
        </Button>
      }
    >
      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={roles}
        columns={[
          { title: '名称', dataIndex: 'name' },
          {
            title: '编码',
            dataIndex: 'code',
            render: (v: string, row) => (
              <Space>
                <Typography.Text code>{v}</Typography.Text>
                {row.is_system ? <Tag>系统</Tag> : null}
              </Space>
            ),
          },
          { title: '说明', dataIndex: 'description' },
          {
            title: '权限数',
            render: (_, row) => row.permission_codes?.length || 0,
          },
          {
            title: '启用',
            dataIndex: 'enabled',
            render: (v: boolean, row) => (
              <Switch
                checked={v}
                disabled={row.code === 'super_admin'}
                onChange={(enabled) => patchMut.mutate({ id: row.id, body: { enabled } })}
              />
            ),
          },
          {
            title: '操作',
            render: (_, row) => (
              <Space>
                <Button size="small" onClick={() => openEdit(row)}>
                  编辑
                </Button>
                <Button size="small" onClick={() => openPerms(row)}>
                  权限
                </Button>
                {!row.is_system ? (
                  <Button size="small" danger onClick={() => deleteMut.mutate(row.id)}>
                    删除
                  </Button>
                ) : null}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑角色' : '新建角色'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={createMut.isPending || patchMut.isPending}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            if (editing) {
              patchMut.mutate({
                id: editing.id,
                body: {
                  name: values.name,
                  description: values.description,
                  enabled: values.enabled,
                },
              })
            } else {
              createMut.mutate(values)
            }
          }}
        >
          <Form.Item
            name="code"
            label="编码"
            rules={[{ required: true, message: '请输入编码' }]}
          >
            <Input disabled={Boolean(editing)} placeholder="例如 content_ops" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`配置权限：${permRole?.name || ''}`}
        open={permOpen}
        width={720}
        onCancel={() => setPermOpen(false)}
        onOk={() => {
          if (!permRole) return
          permMut.mutate({ id: permRole.id, permission_codes: checked })
        }}
        confirmLoading={permMut.isPending}
        destroyOnClose
      >
        <Collapse items={moduleItems} defaultActiveKey={Object.keys(permissionsByModule)} />
      </Modal>
    </Card>
  )
}
