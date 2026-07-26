import { ChatPanel } from './components/Chat/ChatPanel';
import { Dashboard } from './components/Dashboard/Dashboard';
import { DatasetProvider } from './context/DatasetContext';

function App() {
  return (
    <DatasetProvider>
      <div className="app-layout">
        <main className="dashboard-pane">
          <h1>Personal Data Analysis &amp; BI Toolkit</h1>
          <Dashboard />
        </main>
        <aside className="chat-pane">
          <ChatPanel />
        </aside>
      </div>
    </DatasetProvider>
  );
}

export default App;
