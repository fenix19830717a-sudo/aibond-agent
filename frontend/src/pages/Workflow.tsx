import React, { useState, useEffect } from 'react';
import { Card, Button, Modal, Form, Input, List, Tag, Typography, message, Space } from 'antd';
import { PlusOutlined, ApartmentOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { api } from '../api';

const { Title, Text } = Typography;

const Workflow: React.FC = () => {
  const { user } = useAuthStore();
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      const data = await api.listWorkflows();
      setWorkflows(data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      await api.createWorkflow(values.name, values.description || '', user!.id, { nodes: [], edges: [] }, values.trigger_type || 'manual');
      message.success('工作流创建成功');
      setModalOpen(false);
      form.resetFields();
      loadWorkflows();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const triggerLabels: Record<string, string> = {
    manual: '手动触发',
    message: '消息触发',
    schedule: '定时触发',
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>工作流管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>创建工作流</Button>
      </div>
      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3 }}
        dataSource={workflows}
        renderItem={(wf: any) => (
          <List.Item>
            <Card
              title={
                <Space>
                  <ApartmentOutlined />
                  <span>{wf.name}</span>
                </Space>
              }
              extra={
                <Space>
                  <Tag>{triggerLabels[wf.trigger_type] || wf.trigger_type}</Tag>
                  <Button type="link" icon={<PlayCircleOutlined />} onClick={() => navigate(`/workflows/${wf.id}`)}>编辑</Button>
                </Space>
              }
              style={{ cursor: 'pointer', height: '100%' }}
              onClick={() => navigate(`/workflows/${wf.id}`)}
            >
              <Text type="secondary">{wf.description || '暂无描述'}</Text>
              <div style={{ marginTop: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>创建时间: {wf.created_at?.split('T')[0]}</Text>
              </div>
            </Card>
          </List.Item>
        )}
        locale={{ emptyText: '暂无工作流' }}
      />

      <Modal title="创建工作流" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null}>
        <Form form={form} onFinish={handleCreate} layout="vertical">
          <Form.Item name="name" label="工作流名称" rules={[{ required: true }]}>
            <Input placeholder="输入工作流名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="输入工作流描述" rows={3} />
          </Form.Item>
          <Form.Item name="trigger_type" label="触发方式" initialValue="manual">
            <select style={{ width: '100%', padding: '4px 11px', borderRadius: 6, background: '#141414', color: '#fff', border: '1px solid #424242' }}>
              <option value="manual">手动触发</option>
              <option value="message">消息触发</option>
              <option value="schedule">定时触发</option>
            </select>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Workflow;
