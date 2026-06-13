import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { WikiLayout } from './components/wiki/WikiLayout';
import { AgentLayout } from './components/agent/AgentLayout';

const Editor = lazy(() =>
  import('./components/wiki/Editor').then(m => ({ default: m.Editor }))
);
const KnowledgeGrowth = lazy(() =>
  import('./components/wiki/KnowledgeGrowth').then(m => ({ default: m.KnowledgeGrowth }))
);
const Insights = lazy(() =>
  import('./components/wiki/Insights').then(m => ({ default: m.Insights }))
);
const AgentChat = lazy(() =>
  import('./components/agent/AgentChat').then(m => ({ default: m.AgentChat }))
);
const AutoResearchPanel = lazy(() =>
  import('./components/agent/AutoResearchPanel').then(m => ({ default: m.AutoResearchPanel }))
);
const TaskMonitor = lazy(() =>
  import('./components/wiki/TaskMonitor').then(m => ({ default: m.TaskMonitor }))
);
const LLMSettings = lazy(() =>
  import('./components/agent/LLMSettings').then(m => ({ default: m.LLMSettings }))
);
const ReproductionPanel = lazy(() =>
  import('./components/reproduction/ReproductionPanel').then(m => ({ default: m.ReproductionPanel }))
);
const PaperPanel = lazy(() =>
  import('./components/paper/PaperPanel').then(m => ({ default: m.PaperPanel }))
);
const FactorPanel = lazy(() =>
  import('./components/factor/FactorPanel').then(m => ({ default: m.FactorPanel }))
);
const FactorDetail = lazy(() =>
  import('./components/factor/FactorDetail').then(m => ({ default: m.FactorDetail }))
);
const StrategyPanel = lazy(() =>
  import('./components/strategy/StrategyPanel').then(m => ({ default: m.StrategyPanel }))
);

function Loading() {
  return <div className="p-6 text-muted-foreground">Loading...</div>;
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          {/* Wiki routes */}
          <Route path="/" element={<WikiLayout />}>
            <Route index element={<Navigate to="/edit" replace />} />
            <Route path="edit" element={<Editor />} />
            <Route path="dashboard" element={<KnowledgeGrowth />} />
            <Route path="insights" element={<Insights />} />
          </Route>

          {/* Agent routes */}
          <Route path="/agent" element={<AgentLayout />}>
            <Route index element={<Navigate to="/agent/chat" replace />} />
            <Route path="chat" element={<AgentChat />} />
            <Route path="research" element={<Navigate to="/agent/autoresearch" replace />} />
            <Route path="autoresearch" element={<AutoResearchPanel />} />
            <Route path="reproduction" element={<ReproductionPanel />} />
            <Route path="paper" element={<PaperPanel />} />
            <Route path="factor" element={<FactorPanel />} />
            <Route path="factor-library" element={<FactorDetail />} />
            <Route path="factor-library/:name" element={<FactorDetail />} />
            <Route path="strategy" element={<StrategyPanel />} />
            <Route path="tasks" element={<TaskMonitor />} />
            <Route path="settings" element={<LLMSettings />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
