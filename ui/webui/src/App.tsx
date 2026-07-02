import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { WikiLayout } from './components/wiki/WikiLayout';
import { AgentLayout } from './components/agent/AgentLayout';
import { LoginPage } from './components/auth/LoginPage';
import { ProtectedRoute } from './components/auth/ProtectedRoute';

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
const FactorList = lazy(() =>
  import('./components/factor/FactorList').then(m => ({ default: m.FactorList }))
);
const FactorFamilyList = lazy(() =>
  import('./components/factor/FactorFamilyList').then(m => ({ default: m.FactorFamilyList }))
);
const FamilyDetail = lazy(() =>
  import('./components/factor/FamilyDetail').then(m => ({ default: m.FamilyDetail }))
);
const FactorDetail = lazy(() =>
  import('./components/factor/FactorDetail').then(m => ({ default: m.FactorDetail }))
);
const StrategyList = lazy(() =>
  import('./components/strategy/StrategyList').then(m => ({ default: m.StrategyList }))
);
const StrategyDetail = lazy(() =>
  import('./components/strategy/StrategyDetail').then(m => ({ default: m.StrategyDetail }))
);
const BacktestPlatform = lazy(() =>
  import('./components/backtest/BacktestPlatform').then(m => ({ default: m.BacktestPlatform }))
);

function Loading() {
  return <div className="p-6 text-muted-foreground">Loading...</div>;
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected routes */}
          <Route element={<ProtectedRoute />}>
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
              <Route path="factor" element={<FactorFamilyList />} />
              <Route path="factor/fam/:family" element={<FamilyDetail />} />
              <Route path="factor/families" element={<FactorFamilyList />} />
              <Route path="factor/*" element={<FactorDetail />} />
              <Route path="strategy" element={<StrategyList />} />
              <Route path="strategy/:name" element={<StrategyDetail />} />
              <Route path="backtest" element={<BacktestPlatform />} />
              <Route path="tasks" element={<TaskMonitor />} />
              <Route path="settings" element={<LLMSettings />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
