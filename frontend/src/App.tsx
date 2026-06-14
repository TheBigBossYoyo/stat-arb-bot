import { Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import Risk from "./pages/Risk";
import Execution from "./pages/Execution";
import Strategies from "./pages/Strategies";
import Pairs from "./pages/Pairs";
import Backtests from "./pages/Backtests";
import BacktestDetail from "./pages/BacktestDetail";
import Brokers from "./pages/Brokers";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";
import ProductDecisionPage from "./pages/ProductDecisionPage";
import TradabilityMatrixPage from "./pages/TradabilityMatrixPage";
import BlockersPage from "./pages/BlockersPage";
import LiveReadinessPage from "./pages/LiveReadinessPage";
import ConcentrationDiagnosticsPage from "./pages/ConcentrationDiagnosticsPage";
import DeflatedSharpePage from "./pages/DeflatedSharpePage";
import CrisisLabPage from "./pages/CrisisLabPage";
import LongOnlyPaperSetupPage from "./pages/LongOnlyPaperSetupPage";
import Trading212OrderPreviewPage from "./pages/Trading212OrderPreviewPage";
import SupervisedPaperMonitorPage from "./pages/SupervisedPaperMonitorPage";
import OperatorPaperModePage from "./pages/OperatorPaperModePage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/execution" element={<Execution />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/pairs" element={<Pairs />} />
        <Route path="/backtests" element={<Backtests />} />
        <Route path="/backtests/:id" element={<BacktestDetail />} />
        <Route path="/brokers" element={<Brokers />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<Settings />} />
        {/* Tradable-product / paper-readiness */}
        <Route path="/product-decision" element={<ProductDecisionPage />} />
        <Route path="/tradability" element={<TradabilityMatrixPage />} />
        <Route path="/blockers" element={<BlockersPage />} />
        <Route path="/live-readiness" element={<LiveReadinessPage />} />
        <Route path="/concentration" element={<ConcentrationDiagnosticsPage />} />
        <Route path="/deflated-sharpe" element={<DeflatedSharpePage />} />
        <Route path="/crisis-lab" element={<CrisisLabPage />} />
        <Route path="/paper-setup" element={<LongOnlyPaperSetupPage />} />
        <Route path="/order-preview" element={<Trading212OrderPreviewPage />} />
        <Route path="/paper-monitor" element={<SupervisedPaperMonitorPage />} />
        <Route path="/operator" element={<OperatorPaperModePage />} />
      </Routes>
    </Layout>
  );
}
