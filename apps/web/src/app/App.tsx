import { ChatWorkspace } from "../features/chat/components/ChatWorkspace";
import { AuthGate } from "../features/auth/AuthGate";

export const App = () => (
	<AuthGate>
		<ChatWorkspace />
	</AuthGate>
);
