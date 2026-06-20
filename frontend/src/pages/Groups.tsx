import React, { useState, useEffect } from 'react';
import { Card, Button, Modal, Form, Input, List, Tag, Typography, message, Space, Select, Tooltip } from 'antd';
import { PlusOutlined, TeamOutlined, RobotOutlined, UserOutlined, RightOutlined, CrownOutlined, StarOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { api } from '../api';

const { Title, Text } = Typography;

const roleColorMap: Record<string, string> = {
  owner: 'gold',
  lead: 'blue',
  admin: 'purple',
  member: 'default',
  viewer: 'default',
};

const roleLabelMap: Record<string, string> = {
  owner: '群主',
  lead: '队长',
  admin: '管理员',
  member: '成员',
  viewer: '观察者',
};

const Groups: React.FC = () => {
  const { user } = useAuthStore();
  const navigate = useNavigate();
  const [groups, setGroups] = useState<any[]>([]);
  const [availableAgents, setAvailableAgents] = useState<any[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [memberModalOpen, setMemberModalOpen] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<string>('');
  const [memberType, setMemberType] = useState<string>('agent');
  const [form] = Form.useForm();
  const [memberForm] = Form.useForm();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [groupsData, agentsData] = await Promise.all([api.listGroups(), api.listAvailableAgents()]);
      // Fetch detailed group info for each group to get members
      const detailedGroups = await Promise.all(
        groupsData.map(async (g: any) => {
          try {
            const detail = await api.getGroup(g.id);
            return { ...g, ...detail };
          } catch {
            return g;
          }
        })
      );
      setGroups(detailedGroups);
      setAvailableAgents(agentsData);
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreate = async (values: any) => {
    try {
      const group = await api.createGroup(values.name, values.description || '', user!.id);
      // If a lead agent is selected, add it with 'lead' role
      if (values.lead_agent_id) {
        await api.addMember(group.id, 'agent', values.lead_agent_id, 'lead');
      }
      message.success('群组创建成功');
      setModalOpen(false);
      form.resetFields();
      loadData();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleAddMember = async (values: any) => {
    try {
      await api.addMember(selectedGroup, values.member_type, values.member_id, values.role || 'member');
      message.success('成员添加成功');
      setMemberModalOpen(false);
      memberForm.resetFields();
      loadData();
    } catch (err: any) {
      message.error(err.message);
    }
  };

  const handleMemberTypeChange = (type: string) => {
    setMemberType(type);
    memberForm.setFieldValue('member_id', undefined);
  };

  const handleGroupClick = (_groupId: string) => {
    navigate('/');
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>群组管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>创建群组</Button>
      </div>
      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={groups}
        renderItem={(group: any) => (
          <List.Item>
            <Card
              title={
                <Space>
                  <TeamOutlined />
                  <span>{group.name}</span>
                </Space>
              }
              extra={
                <Button
                  type="link"
                  icon={<PlusOutlined />}
                  onClick={(e) => { e.stopPropagation(); setSelectedGroup(group.id); setMemberModalOpen(true); setMemberType('agent'); memberForm.resetFields(); memberForm.setFieldValue('member_type', 'agent'); }}
                >
                  添加成员
                </Button>
              }
              style={{ height: '100%', cursor: 'pointer' }}
              hoverable
              onClick={() => handleGroupClick(group.id)}
            >
              <Text type="secondary">{group.description || '暂无描述'}</Text>

              {/* 成员列表 */}
              {group.members && group.members.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                    成员 ({group.members.length})
                  </Text>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {group.members.slice(0, 6).map((member: any, idx: number) => (
                      <Tooltip
                        key={idx}
                        title={`${member.name || member.member_name || member.id || member.member_id} - ${roleLabelMap[member.role] || member.role}`}
                      >
                        <Tag
                          color={roleColorMap[member.role] || 'default'}
                          style={{ cursor: 'default' }}
                        >
                          {member.type === 'agent' || member.member_type === 'agent' ? (
                            <Space size={4}>
                              <RobotOutlined />
                              <span>{member.name || member.member_name || member.id?.slice(0, 8) || member.member_id?.slice(0, 8)}</span>
                            </Space>
                          ) : (
                            <Space size={4}>
                              <UserOutlined />
                              <span>{member.name || member.member_name || member.id?.slice(0, 8) || member.member_id?.slice(0, 8)}</span>
                            </Space>
                          )}
                          {member.role && (
                            <span style={{ opacity: 0.7, fontSize: 10, marginLeft: 4 }}>
                              {roleLabelMap[member.role] || member.role}
                            </span>
                          )}
                        </Tag>
                      </Tooltip>
                    ))}
                    {group.members.length > 6 && (
                      <Tag>+{group.members.length - 6}</Tag>
                    )}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>创建时间: {group.created_at?.split('T')[0]}</Text>
                <Button type="link" size="small" icon={<RightOutlined />} onClick={() => handleGroupClick(group.id)}>
                  进入聊天
                </Button>
              </div>
            </Card>
          </List.Item>
        )}
      />

      <Modal title="创建群组" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null}>
        <Form form={form} onFinish={handleCreate} layout="vertical">
          <Form.Item name="name" label="群组名称" rules={[{ required: true }]}>
            <Input placeholder="输入群组名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="输入群组描述" rows={3} />
          </Form.Item>
          <Form.Item name="lead_agent_id" label="队长 Agent（可选）">
            <Select
              style={{ width: '100%' }}
              placeholder="选择一个 Agent 作为队长"
              allowClear
              showSearch
              optionFilterProp="children"
              options={availableAgents.map((a: any) => ({
                value: a.id,
                label: `${a.name} (${a.status})`,
              }))}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="添加成员" open={memberModalOpen} onCancel={() => setMemberModalOpen(false)} footer={null}>
        <Form form={memberForm} onFinish={handleAddMember} layout="vertical">
          <Form.Item name="member_type" label="成员类型" rules={[{ required: true }]} initialValue="agent">
            <Select
              style={{ width: '100%' }}
              onChange={handleMemberTypeChange}
              options={[
                { value: 'agent', label: 'AI Agent' },
                { value: 'user', label: '用户' },
              ]}
            />
          </Form.Item>
          {memberType === 'agent' ? (
            <Form.Item name="member_id" label="选择 Agent" rules={[{ required: true, message: '请选择一个 Agent' }]}>
              <Select
                style={{ width: '100%' }}
                placeholder="选择要添加的 Agent"
                showSearch
                optionFilterProp="children"
                options={availableAgents.map((a: any) => ({
                  value: a.id,
                  label: `${a.name} (${a.status})`,
                }))}
              />
            </Form.Item>
          ) : (
            <Form.Item name="member_id" label="用户 ID" rules={[{ required: true, message: '请输入用户 ID' }]}>
              <Input placeholder="输入用户ID" />
            </Form.Item>
          )}
          <Form.Item name="role" label="角色" initialValue="member">
            <Select
              style={{ width: '100%' }}
              options={[
                { value: 'lead', label: <Space><StarOutlined /> 队长</Space> },
                { value: 'admin', label: <Space><CrownOutlined /> 管理员</Space> },
                { value: 'member', label: '成员' },
                { value: 'viewer', label: '观察者' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>添加</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default Groups;
