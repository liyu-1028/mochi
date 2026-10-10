import { useEffect } from "react";
import { useAppUpdates } from "../store/appUpdates";

/** Success is cached hourly; failures retry after five minutes, including a late sidecar. */
export function useAppUpdateChecks(): void {
  useEffect(() => {
    const check = () => void useAppUpdates.getState().check();
    check();
    const timer = setInterval(check, 5 * 60_000);
    window.addEventListener("focus", check);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", check);
    };
  }, []);
}
