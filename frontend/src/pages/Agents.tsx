import React, { useState, useEffect } from 'react';
import { Card, Button, Modal, Form, Input, List, Tag, Typography, message, Space, Badge, Tooltip, Tabs } from 'antd';
import { PlusOutlined, RobotOutlined, ApiOutlined, HeartOutlined, CopyOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { api } from '../api';

const { Title, Text, Paragraph } = Typography;

const Agents: React.FC = () => {
  const [agents, setAgents] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [resultModalOpen, setResultModalOpen] = useState(false);
  const [registerResult, setRegisterResult] = useState<any>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    loadAgents();
    const timer = setInterval(loadAgents, 10000);
    return () => clearInterval(timer);
  }, []);

  const loadAgents = async () => {
    try {
      const data = await api.listAgents();
      // 后端返回的数据可能是 { value: [...] } 或 [...]
      const agentList = Array.isArray(data) ? data : (data?.value || []);
      setAgents(agentList);
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      const data = await api.createAgentToken(values.name);
      setRegisterResult(data);
      setModalOpen(false);
      setResultModalOpen(true);
      form.resetFields();
      loadAgents();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const copyField = (field: string, value: string) => {
    if (value) {
      navigator.clipboard.writeText(value);
      setCopiedField(field);
      message.success('已复制');
      setTimeout(() => setCopiedField(null), 2000);
    }
  };

  const statusConfig: Record<string, { color: 'default' | 'success' | 'warning' | 'processing' | 'error'; label: string; icon: React.ReactNode }> = {
    online: { color: 'success', label: '在线', icon: <CheckCircleOutlined /> },
    offline: { color: 'default', label: '离线', icon: <ClockCircleOutlined /> },
    pending: { color: 'warning', label: '等待连接', icon: <ClockCircleOutlined /> },
    busy: { color: 'processing', label: '忙碌', icon: <ClockCircleOutlined /> },
  };

  const CopyBtn = ({ field, value }: { field: string; value: string }) => (
    <Tooltip title="复制">
      <Button
        type="text"
        size="small"
        icon={copiedField === field ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
        onClick={() => copyField(field, value)}
      />
    </Tooltip>
  );

  const CodeBlock = ({ field, value, language = 'bash' }: { field: string; value: string; language?: string }) => (
    <div style={{
      background: '#1a1a1a',
      border: '1px solid #333',
      borderRadius: 8,
      padding: '12px 16px',
      position: 'relative',
      marginTop: 8,
    }}>
      <code style={{ fontSize: 13, color: language === 'json' ? '#faad14' : '#52c41a', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
        {value}
      </code>
      <div style={{ position: 'absolute', top: 8, right: 8 }}>
        <CopyBtn field={field} value={value} />
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>Agent 管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>注册 Agent</Button>
      </div>
      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={agents}
        renderItem={(agent: any) => {
          const sc = statusConfig[agent.status] || statusConfig.offline;
          return (
            <List.Item>
              <Card
                title={
                  <Space>
                    <Badge status={sc.color} />
                    <RobotOutlined />
                    <span>{agent.name}</span>
                  </Space>
                }
                extra={<Tag color={sc.color} icon={sc.icon}>{sc.label}</Tag>}
              >
                {agent.skills && agent.skills.length > 0 ? (
                  <div style={{ marginBottom: 8 }}>
                    {agent.skills.map((skill: string) => (
                      <Tag key={skill} icon={<ApiOutlined />} style={{ marginBottom: 2 }}>{skill}</Tag>
                    ))}
                  </div>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12, fontStyle: 'italic' }}>
                    {agent.status === 'pending' ? '等待 Agent 连接后自动发现 Skills...' : '暂无 Skills'}
                  </Text>
                )}
                <div style={{ marginTop: 8 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <HeartOutlined /> 最后心跳: {agent.last_heartbeat ? new Date(agent.last_heartbeat).toLocaleString() : '从未'}
                  </Text>
                </div>
              </Card>
            </List.Item>
          );
        }}
        locale={{ emptyText: '暂无注册的 Agent' }}
      />

      {/* 注册弹窗 */}
      <Modal title="注册新 Agent" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null}>
        <Paragraph type="secondary">只需输入 Agent 名称，系统将生成完整的连接指南。</Paragraph>
        <Form form={form} onFinish={handleCreate} layout="vertical">
          <Form.Item name="name" label="Agent 名称" rules={[{ required: true, message: '请输入 Agent 名称' }]}>
            <Input placeholder="例如：代码审查助手" size="large" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block size="large">生成连接指南</Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* 注册结果弹窗 - 完整连接指南 */}
      <Modal
        title="Agent 连接指南已生成"
        open={resultModalOpen}
        onCancel={() => setResultModalOpen(false)}
        footer={<Button onClick={() => setResultModalOpen(false)}>关闭</Button>}
        width={680}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <Text type="secondary">Agent 名称</Text><br />
              <Text strong>{registerResult?.name}</Text>
            </div>
            <div>
              <Text type="secondary">Agent ID</Text><br />
              <Space>
                <Text code style={{ fontSize: 11 }}>{registerResult?.id}</Text>
                <CopyBtn field="id" value={registerResult?.id || ''} />
              </Space>
            </div>
            <div>
              <Text type="secondary">API Key</Text><br />
              <Space>
                <Text code style={{ fontSize: 11 }}>{registerResult?.api_key}</Text>
                <CopyBtn field="apikey" value={registerResult?.api_key || ''} />
              </Space>
            </div>
          </div>

          <Tag color="warning" icon={<ClockCircleOutlined />}>等待连接</Tag>

          <Tabs
            size="small"
            items={[
              {
                key: 'cli',
                label: 'CLI 连接',
                children: (
                  <div>
                    <Text type="secondary">1. 安装 SDK</Text>
                    <CodeBlock field="install" value="pip install aibond-agent" />
                    <Text type="secondary" style={{ marginTop: 12, display: 'block' }}>2. 连接平台</Text>
                    <CodeBlock field="connect" value={registerResult?.register_command || ''} />
                  </div>
                ),
              },
              {
                key: 'mcp',
                label: 'MCP 配置',
                children: (
                  <div>
                    <Text type="secondary">在 Claude Desktop / Trae 等客户端的 MCP 配置中添加：</Text>
                    <CodeBlock field="mcp" value={registerResult?.mcp_config || ''} language="json" />
                  </div>
                ),
              },
              {
                key: 'sdk',
                label: 'Python SDK',
                children: (
                  <div>
                    <Text type="secondary">在 Python 代码中使用：</Text>
                    <CodeBlock field="sdk" value={`from aibond_agent import AibondClient\n\nclient = AibondClient(\n    server="${registerResult?.server_url || ''}",\n    token="${registerResult?.api_key || ''}",\n    name="${registerResult?.name || ''}"\n)\nclient.on_message(lambda msg: print(msg))\nclient.connect()`} language="python" />
                  </div>
                ),
              },
              {
                key: 'full',
                label: '完整指南',
                children: (
                  <div>
                    <Text type="secondary">完整的连接指南（可复制发送给 Agent）：</Text>
                    <CodeBlock field="guide" value={registerResult?.connection_guide || ''} />
                  </div>
                ),
              },
            ]}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default Agents;
