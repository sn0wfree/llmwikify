import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { WikiLayout } from './components/wiki/WikiLayout';
import { AgentLayout } from './components/agent/AgentLayout';
import { LoginPage } from './components/auth/LoginPage';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { AuthInitBanner } from './components/auth/AuthInitBanner';

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
// v0.40 BREAKING: removed quant panel routes (ReproductionPanel, PaperPanel,
// FactorList, FactorFamilyList, FamilyDetail, FactorDetail, StrategyList,
// StrategyDetail, BacktestPlatform). Quant UI now lives in quantnodes."

function Loading() {
  return <div className="p-6 text-muted-foreground">Loading...</div>;
}

function App() {
  return (
    <BrowserRouter>
      <AuthInitBanner />
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
              <Route path="tasks" element={<TaskMonitor />} />
              <Route path="settings" element={<LLMSettings />} />
              {/* v0.40: removed /reproduction, /paper, /factor/*, /strategy/*, /backtest
                  — moved to quantnodes (https://github.com/sn0wfree/quantnodes) */}
              <Route
                path="reproduction"
                element={<Navigate to="/agent/chat?notice=reproduction-moved-to-quantnodes" replace />}
              />
              <Route
                path="paper"
                element={<Navigate to="/agent/chat?notice=paper-moved-to-quantnodes" replace />}
              />
              <Route
                path="factor/*"
                element={<Navigate to="/agent/chat?notice=factor-moved-to-quantnodes" replace />}
              />
              <Route
                path="strategy/*"
                element={<Navigate to="/agent/chat?notice=strategy-moved-to-quantnodes" replace />}
              />
              <Route
                path="backtest"
                element={<Navigate to="/agent/chat?notice=backtest-moved-to-quantnodes" replace />}
              />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default App;
