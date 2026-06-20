import React, { useState } from 'react';
import { Form, Input, Button, Card, Typography, message, Tabs } from 'antd';
import { UserOutlined, LockOutlined, RobotOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { api } from '../api';

const { Title, Text } = Typography;

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const data = await api.login(values.username, values.password);
      setAuth(data.token, data.user);
      message.success('登录成功');
      navigate('/');
    } catch (err: any) {
      message.error(err.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (values: { username: string; password: string; email?: string; confirmPassword?: string }) => {
    // Client-side password validation
    if (values.password.length < 8) {
      message.error('密码至少需要8位字符');
      return;
    }
    if (!/[A-Za-z]/.test(values.password) || !/\d/.test(values.password)) {
      message.error('密码必须同时包含字母和数字');
      return;
    }
    if (values.password !== values.confirmPassword) {
      message.error('两次输入的密码不一致');
      return;
    }
    if (values.username.length < 3 || values.username.length > 50) {
      message.error('用户名长度应为3-50个字符');
      return;
    }
    if (!/^[a-zA-Z0-9_\-\.]+$/.test(values.username)) {
      message.error('用户名只能包含字母、数字、下划线、横线和点');
      return;
    }

    setLoading(true);
    try {
      const data = await api.register(values.username, values.password, values.email);
      setAuth(data.token, data.user);
      message.success('注册成功');
      navigate('/');
    } catch (err: any) {
      message.error(err.message || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#141414' }}>
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <RobotOutlined style={{ fontSize: 48, color: '#1677ff' }} />
          <Title level={3} style={{ marginTop: 8 }}>aibond</Title>
          <Text type="secondary">企业人机协同路由平台</Text>
        </div>
        <Tabs
          centered
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form onFinish={handleLogin} layout="vertical">
                  <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                    <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
                  </Form.Item>
                  <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} block>
                      登录
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form onFinish={handleRegister} layout="vertical">
                  <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                    <Input prefix={<UserOutlined />} placeholder="用户名（3-50位，字母数字下划线）" autoComplete="username" />
                  </Form.Item>
                  <Form.Item name="email">
                    <Input placeholder="邮箱（可选）" autoComplete="email" />
                  </Form.Item>
                  <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="密码（至少8位，含字母和数字）" autoComplete="new-password" />
                  </Form.Item>
                  <Form.Item name="confirmPassword" rules={[{ required: true, message: '请确认密码' }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} block>
                      注册
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default Login;
