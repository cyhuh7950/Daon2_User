import { WebNotificationInboxWorkspace } from "../../components/notification-inbox-workspace.jsx";
import navigation from "@daon2-user/contracts/navigation.json";
import screens from "@daon2-user/contracts/screens.json";

const route = navigation.routes.find((item) => item.route_id === "inbox");
const screen = screens.screens.find((item) => item.screen_id === "inbox");

export default function InboxPage() {
  return <WebNotificationInboxWorkspace mode="inbox" routeId={route.route_id} screenId={screen.screen_id} />;
}
