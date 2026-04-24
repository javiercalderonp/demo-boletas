export type BackofficeUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  active: boolean;
};

export type Employee = {
  phone: string;
  first_name?: string;
  last_name?: string;
  name: string;
  rut?: string;
  email?: string;
  company_id?: string;
  bank_name?: string;
  account_type?: string;
  account_number?: string;
  account_holder?: string;
  account_holder_rut?: string;
  active: boolean;
  last_activity_at?: string;
  case_count?: number;
  expense_count?: number;
};

export type Company = {
  company_id: string;
  name: string;
  rut?: string;
  bank_name?: string;
  account_type?: string;
  account_number?: string;
  account_holder?: string;
  account_holder_rut?: string;
  finance_email?: string;
  active: boolean;
};

export type CaseItem = {
  case_id: string;
  context_label?: string;
  company_id?: string;
  employee_phone?: string;
  phone?: string;
  closure_method?: string;
  status: string;
  fondos_entregados?: number | string;
  rendicion_status?: string;
  user_confirmed_at?: string;
  user_confirmation_status?: string;
  monto_rendido_aprobado?: number;
  monto_pendiente_revision?: number;
  saldo_restante?: number;
  settlement_direction?: string;
  settlement_status?: string;
  settlement_amount_clp?: number | string;
  settlement_net_clp?: number | string;
  settlement_calculated_at?: string;
  settlement_resolved_at?: string;
  created_at?: string;
  updated_at?: string;
  notes?: string;
  employee?: Employee;
  expense_count?: number;
};

export type Expense = {
  expense_id: string;
  case_id: string;
  phone: string;
  merchant?: string;
  date?: string;
  currency?: string;
  total?: number | string;
  total_clp?: number | string;
  category?: string;
  country?: string;
  shared?: boolean | string;
  status?: string;
  image_url?: string;
  document_url?: string;
  created_at?: string;
  updated_at?: string;
  employee?: Employee;
  case?: CaseItem;
  review_score?: number;
  review_status?: string;
  review_breakdown?: Record<string, number>;
  review_flags?: string[];
  primary_review_reason?: string;
  document_type?: string;
  invoice_number?: string;
  tax_amount?: number | string;
  issuer_tax_id?: string;
  receiver_tax_id?: string;
  gross_amount?: number | string;
  withholding_rate?: number | string;
  withholding_amount?: number | string;
  net_amount?: number | string;
  receiver_name?: string;
  service_description?: string;
};

export type Conversation = {
  phone: string;
  case_id?: string;
  state: string;
  current_step?: string;
  context_json: ConversationContext;
  updated_at?: string;
  employee?: Employee;
  case?: CaseItem;
};

export type ConversationMessage = {
  id: string;
  speaker: "person" | "bot" | "operator" | string;
  type: "text" | "media" | string;
  text: string;
  created_at?: string;
  message_id?: string;
  operator_name?: string;
};

export type ConversationContext = Record<string, unknown> & {
  message_log?: ConversationMessage[];
};

export type DashboardData = {
  stats: {
    active_employees: number;
    rendiciones_open: number;
    rendiciones_pending: number;
    total_fondos: number;
    total_rendido_aprobado: number;
    total_pendiente_revision: number;
    total_saldo: number;
    docs_needs_review: number;
    active_conversations: number;
  };
  rendicion_status_distribution?: Record<string, number>;
  rendiciones: CaseItem[];
  latest_expenses: Expense[];
  latest_conversations: Conversation[];
  alerts: { type: string; severity?: string; message: string; case_id?: string; expense_id?: string }[];
};
