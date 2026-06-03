/**
 * Route table (frontend-spec §3): /login is public; everything else sits behind
 * the AuthGuard inside the AppShell.
 */
import { createBrowserRouter } from "react-router"

import { AppShell } from "@/app/AppShell"
import { AuthGuard } from "@/app/AuthGuard"
import { AIReportPage } from "@/features/ai-report/AIReportPage"
import { ArticlesPage } from "@/features/articles/ArticlesPage"
import { CustomerDetailPage } from "@/features/customers/CustomerDetailPage"
import { ChatPage } from "@/features/chat/ChatPage"
import { CustomersPage } from "@/features/customers/CustomersPage"
import { DashboardPage } from "@/features/dashboard/DashboardPage"
import { LoginPage } from "@/features/login/LoginPage"
import { OpportunitiesPage } from "@/features/opportunities/OpportunitiesPage"
import { SettingsPage } from "@/features/settings/SettingsPage"
import { TasksPage } from "@/features/tasks/TasksPage"

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "/zadaci", element: <TasksPage /> },
          { path: "/kupci", element: <CustomersPage /> },
          { path: "/kupci/:customerId", element: <CustomerDetailPage /> },
          { path: "/artikli", element: <ArticlesPage /> },
          { path: "/prilike", element: <OpportunitiesPage /> },
          { path: "/ai-report", element: <AIReportPage /> },
          { path: "/chat", element: <ChatPage /> },
          { path: "/postavke", element: <SettingsPage /> },
        ],
      },
    ],
  },
])
