import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './components/MainLayout';
import Login from './pages/Login';
import Chat from './pages/Chat';
import Groups from './pages/Groups';
import Workflow from './pages/Workflow';
import WorkflowEditor from './pages/WorkflowEditor';
import Agents from './pages/Agents';
import { useAuthStore } from './store/authStore';

const App: React.FC = () => {
  const { token } = useAuthStore();

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 8,
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={token ? <Navigate to="/" /> : <Login />} />
          <Route path="/" element={token ? <MainLayout /> : <Navigate to="/login" />}>
            <Route index element={<Chat />} />
            <Route path="groups" element={<Groups />} />
            <Route path="agents" element={<Agents />} />
            <Route path="workflows" element={<Workflow />} />
            <Route path="workflows/:id" element={<WorkflowEditor />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;
