import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

let permitted: boolean | null = null;

export async function notify(title: string, body: string) {
  if (permitted === null) {
    permitted = await isPermissionGranted();
    if (!permitted) {
      const p = await requestPermission();
      permitted = p === "granted";
    }
  }
  if (permitted) {
    sendNotification({ title, body });
  }
}
