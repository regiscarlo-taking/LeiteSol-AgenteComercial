import { jsx as _jsx } from "react/jsx-runtime";
import { ChatWorkspace } from "../features/chat/components/ChatWorkspace";
import { AuthGate } from "../features/auth/AuthGate";
export const App = () => (_jsx(AuthGate, { children: _jsx(ChatWorkspace, {}) }));
