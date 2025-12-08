import { useState } from "react";
import type { TabId } from "./types/domain";
import { RestaurantsTab } from "./components/RestaurantsTab";
import { PersonasTab } from "./components/PersonasTab";
import { PhrasesTab } from "./components/PhrasesTab";
import { ConfigTab } from "./components/ConfigTab";
import { AutomationTab } from "./components/AutomationTab";
import { ReportsTab } from "./components/ReportsTab";

function App() {
  const [activeTab, setActiveTab] = useState<TabId>("automation");

  function renderTabButton(id: TabId, label: string) {
    const isActive = activeTab === id;
    return (
      <button
        key={id}
        onClick={() => setActiveTab(id)}
        className={`px-3 py-1 rounded-md text-sm font-medium border transition-colors ${
          isActive
            ? "bg-slate-100 text-slate-900 border-slate-300"
            : "bg-slate-900 text-slate-200 border-slate-700 hover:bg-slate-800"
        }`}
      >
        {label}
      </button>
    );
  }

  function renderActiveTab() {
    if (activeTab === "restaurants") return <RestaurantsTab />;
    if (activeTab === "personas") return <PersonasTab />;
    if (activeTab === "phrases") return <PhrasesTab />;
    if (activeTab === "config") return <ConfigTab />;
    if (activeTab === "automation") return <AutomationTab />;
    if (activeTab === "reports") return <ReportsTab />;
    return null;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 flex items-center justify-center">
      <div className="w-full max-w-5xl mx-auto px-4 py-6">
        <div className="rounded-xl bg-slate-900/80 border border-slate-800 shadow-xl p-4 md:p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold">FastSocial</h1>
              <p className="text-slate-400 text-xs mt-1">
                Painel de geranciamento e controle de fluxo de automações.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {renderTabButton("restaurants", "Restaurantes")}
              {renderTabButton("personas", "Personas")}
              {renderTabButton("phrases", "Frases")}
              {renderTabButton("config", "Config")}
              {renderTabButton("automation", "Automação")}
              {renderTabButton("reports", "Relatórios")}
            </div>
          </div>

          <div className="pt-2 border-t border-slate-800">
            {renderActiveTab()}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;