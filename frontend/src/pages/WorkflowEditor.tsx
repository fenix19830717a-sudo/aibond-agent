import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, Space, Typography, message, Card, Select, Input, InputNumber, Tag, Drawer, Divider, Empty } from 'antd';
import {
  SaveOutlined,
  PlayCircleOutlined,
  ArrowLeftOutlined,
  PlusOutlined,
  RobotOutlined,
  UserOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  SendOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import ReactFlow, {
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  Controls,
  Background,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  MarkerType,
} from 'reactflow';
import 'reactflow/dist/style.css';
const { Title, Text } = Typography;
const { TextArea } = Input;
const nodeTypesConfig = {
  trigger: { label: '触发节点', icon: <ThunderboltOutlined />, color: '#faad14' },
  ai: { label: 'AI 执行', icon: <RobotOutlined />, color: '#52c41a' },
  human: { label: '人工审核', icon: <UserOutlined />, color: '#1677ff' },
  condition: { label: '条件分支', icon: <BranchesOutlined />, color: '#722ed1' },
  output: { label: '输出节点', icon: <SendOutlined />, color: '#eb2f96' },
};
const defaultNodes: Node[] = [
  {
    id: '1',
    type: 'default',
    position: { x: 250, y: 50 },
    data: { label: '开始', nodeType: 'trigger', config: {} },
    style: { background: '#faad14', color: '#fff', padding: '10px 20px', borderRadius: 8, fontSize: 14 },
  },
];
const defaultEdges: Edge[] = [];
const WorkflowEditor: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [nodes, setNodes] = useState<Node[]>(defaultNodes);
  const [edges, setEdges] = useState<Edge[]>(defaultEdges);
  const [workflow, setWorkflow] = useState<any>(null);
  const [addingNode, setAddingNode] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [availableAgents, setAvailableAgents] = useState<any[]>([]);
  useEffect(() => {
    if (id) loadWorkflow();
    loadAgents();
  }, [id]);
  const loadWorkflow = async () => {
    try {
      const { api } = await import('../api');
      const data = await api.getWorkflow(id!);
      setWorkflow(data);
      if (data.definition?.nodes?.length > 0) {
        setNodes(data.definition.nodes);
        setEdges(data.definition.edges || []);
      }
    } catch (err) {
      console.error(err);
    }
  };
  const loadAgents = async () => {
    try {
      const { api } = await import('../api');
      const data = await api.listAvailableAgents();
      setAvailableAgents(data);
    } catch (err) {
      console.error(err);
    }
  };
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds));
  }, []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((eds) => applyEdgeChanges(changes, eds));
  }, []);
  const onConnect = useCallback((connection: Connection) => {
    setEdges((eds) => addEdge({ ...connection, markerEnd: { type: MarkerType.ArrowClosed } }, eds));
  }, []);
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
    setDrawerOpen(true);
  }, []);
  const handleAddNode = (type: string) => {
    const config = nodeTypesConfig[type as keyof typeof nodeTypesConfig];
    const newNode: Node = {
      id: `${Date.now()}`,
      type: 'default',
      position: { x: 250 + Math.random() * 200, y: 100 + nodes.length * 120 },
      data: {
        label: config.label,
        nodeType: type,
        config: type === 'ai' ? { agent_id: '', task_description: '', timeout: 60 } : {},
      },
      style: { background: config.color, color: '#fff', padding: '10px 20px', borderRadius: 8, fontSize: 14, minWidth: 120 },
    };
    setNodes((nds) => [...nds, newNode]);
    setAddingNode(null);
  };
  const updateNodeConfig = (key: string, value: any) => {
    if (!selectedNode) return;
    const updatedData = {
      ...selectedNode.data,
      config: { ...selectedNode.data.config, [key]: value },
    };
    if (key === 'agent_id') {
      const agent = availableAgents.find((a: any) => a.id === value);
      if (agent) {
        updatedData.label = agent.name;
      }
    }
    const updatedNode = { ...selectedNode, data: updatedData };
    setSelectedNode(updatedNode);
    setNodes((nds) => nds.map((n) => (n.id === updatedNode.id ? updatedNode : n)));
  };
  const handleSave = async () => {
    try {
      const { api } = await import('../api');
      await api.updateWorkflowDefinition(id!, { nodes, edges });
      message.success('工作流已保存');
    } catch (err: any) {
      message.error(err.message);
    }
  };
  const handleRun = async () => {
    try {
      const { api } = await import('../api');
      const data = await api.runWorkflow(id!);
      if (data.first_ai_agent) {
        message.success(`工作流已启动，AI 执行者已指定`);
      } else {
        message.success(`工作流已启动，实例ID: ${data.instance_id}`);
      }
    } catch (err: any) {
      message.error(err.message);
    }
  };
  const selectedNodeType = selectedNode?.data?.nodeType;
  const selectedConfig = selectedNode?.data?.config || {};
  return (
    <div style={{ height: 'calc(100vh - 160px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/workflows')}>返回</Button>
          <Title level={4} style={{ margin: 0 }}>{workflow?.name || '工作流编辑器'}</Title>
        </Space>
        <Space>
          <div style={{ position: 'relative' }}>
            <Button icon={<PlusOutlined />} onClick={() => setAddingNode(addingNode ? null : 'menu')}>添加节点</Button>
            {addingNode && (
              <Card style={{ position: 'absolute', top: '100%', right: 0, zIndex: 100, width: 200, marginTop: 4 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {Object.entries(nodeTypesConfig).map(([type, config]) => (
                    <Button
                      key={type}
                      block
                      style={{ textAlign: 'left', borderColor: config.color }}
                      onClick={() => handleAddNode(type)}
                    >
                      <Space>
                        <span style={{ color: config.color }}>{config.icon}</span>
                        <span>{config.label}</span>
                      </Space>
                    </Button>
                  ))}
                </Space>
              </Card>
            )}
          </div>
          <Button icon={<SaveOutlined />} onClick={handleSave}>保存</Button>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun}>运行</Button>
        </Space>
      </div>
      <div style={{ height: 'calc(100% - 50px)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          fitView
        >
          <Controls />
          <Background />
        </ReactFlow>
      </div>
      {/* 节点配置抽屉 */}
      <Drawer
        title={
          <Space>
            <SettingOutlined />
            <span>节点配置</span>
            {selectedNode && (
              <Tag color={nodeTypesConfig[selectedNodeType as keyof typeof nodeTypesConfig]?.color}>
                {nodeTypesConfig[selectedNodeType as keyof typeof nodeTypesConfig]?.label}
              </Tag>
            )}
          </Space>
        }
        placement="right"
        width={360}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {selectedNode ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Text strong>节点 ID：</Text>
              <Text code>{selectedNode.id}</Text>
            </div>
            <Divider style={{ margin: '8px 0' }}>节点名称</Divider>
            <Input
              value={selectedNode.data?.label || ''}
              onChange={(e) => {
                const updatedNode = { ...selectedNode, data: { ...selectedNode.data, label: e.target.value } };
                setSelectedNode(updatedNode);
                setNodes((nds) => nds.map((n) => (n.id === updatedNode.id ? updatedNode : n)));
              }}
              placeholder="节点名称"
            />
            {/* AI 节点专属配置 */}
            {selectedNodeType === 'ai' && (
              <>
                <Divider style={{ margin: '8px 0' }}>AI 执行者</Divider>
                {availableAgents.length > 0 ? (
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择执行此任务的 Agent"
                    value={selectedConfig.agent_id || undefined}
                    onChange={(val) => updateNodeConfig('agent_id', val)}
                    showSearch
                    options={availableAgents.map((a: any) => ({
                      value: a.id,
                      label: `${a.name} (${a.status})`,
                    }))}
                  />
                ) : (
                  <Empty description="暂无可用 Agent，请先注册 Agent" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                )}
                {selectedConfig.agent_id && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>Agent Skills：</Text>
                    <div style={{ marginTop: 4 }}>
                      {availableAgents
                        .filter((a) => a.id === selectedConfig.agent_id)
                        .flatMap((a) => a.skills || [])
                        .map((skill: string) => (
                          <Tag key={skill} color="blue" style={{ marginBottom: 2 }}>{skill}</Tag>
                        ))}
                      {availableAgents.filter((a) => a.id === selectedConfig.agent_id).flatMap((a) => a.skills || []).length === 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>暂无 Skills</Text>
                      )}
                    </div>
                  </div>
                )}
                <Divider style={{ margin: '8px 0' }}>任务描述</Divider>
                <TextArea
                  value={selectedConfig.task_description || ''}
                  onChange={(e) => updateNodeConfig('task_description', e.target.value)}
                  placeholder="描述这个 AI 节点需要执行的任务..."
                  rows={3}
                />
                <Divider style={{ margin: '8px 0' }}>超时设置</Divider>
                <InputNumber
                  style={{ width: '100%' }}
                  min={5}
                  max={3600}
                  value={selectedConfig.timeout || 60}
                  onChange={(val) => updateNodeConfig('timeout', val)}
                  addonAfter="秒"
                />
              </>
            )}
            {/* 人工审核节点 */}
            {selectedNodeType === 'human' && (
              <>
                <Divider style={{ margin: '8px 0' }}>审核说明</Divider>
                <TextArea
                  value={selectedConfig.review_instruction || ''}
                  onChange={(e) => updateNodeConfig('review_instruction', e.target.value)}
                  placeholder="描述审核标准和要求..."
                  rows={3}
                />
              </>
            )}
            {/* 触发节点 */}
            {selectedNodeType === 'trigger' && (
              <>
                <Divider style={{ margin: '8px 0' }}>触发方式</Divider>
                <Select
                  style={{ width: '100%' }}
                  value={selectedConfig.trigger_type || 'manual'}
                  onChange={(val) => updateNodeConfig('trigger_type', val)}
                  options={[
                    { value: 'manual', label: '手动触发' },
                    { value: 'message', label: '消息触发' },
                    { value: 'schedule', label: '定时触发' },
                  ]}
                />
              </>
            )}
            {/* 输出节点 */}
            {selectedNodeType === 'output' && (
              <>
                <Divider style={{ margin: '8px 0' }}>输出目标</Divider>
                <Select
                  style={{ width: '100%' }}
                  value={selectedConfig.output_target || 'group'}
                  onChange={(val) => updateNodeConfig('output_target', val)}
                  options={[
                    { value: 'group', label: '发送到群组' },
                    { value: 'log', label: '记录日志' },
                    { value: 'webhook', label: 'Webhook 回调' },
                  ]}
                />
              </>
            )}
          </Space>
        ) : (
          <Empty description="点击画布中的节点进行配置" />
        )}
      </Drawer>
    </div>
  );
};
export default WorkflowEditor;
