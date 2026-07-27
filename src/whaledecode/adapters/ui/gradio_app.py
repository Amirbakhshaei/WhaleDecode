import asyncio

import gradio as gr

from whaledecode.adapters.chain.factory import create_chain_provider
from whaledecode.adapters.db.session import create_session_factory
from whaledecode.adapters.db.uow import UnitOfWork
from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
from whaledecode.application.services.investigation import InvestigationService
from whaledecode.application.services.wallet import WalletService
from whaledecode.config.settings import Settings


def _init_services():
    settings = Settings()
    session_factory = create_session_factory(settings)

    async def _uow() -> UnitOfWork:
        return UnitOfWork(session_factory)

    reasoner = LangGraphReasoner(settings)
    chain = create_chain_provider(settings)
    investigation = InvestigationService(_uow, reasoner)
    wallets = WalletService(_uow)
    return settings, _uow, investigation, wallets, chain


def create_gradio_app():
    settings, uow, investigation, wallets, chain = _init_services()

    async def chat_fn(message: str, history: list) -> str:
        response = await investigation.chat(message)
        return response

    async def wallet_list_fn(chain_filter: str) -> list[list]:
        chain = chain_filter if chain_filter != "All" else None
        wallets_list = await wallets.list_curated(chain)
        return [[w.id, w.address[:10] + "...", w.chain.value, w.label, w.quality_score] for w in wallets_list]

    async def event_list_fn() -> list[list]:
        async with uow() as uow_instance:
            events = await uow_instance.candidate_events.list_by_status("AGENT_QUEUED", limit=20)
            return [[e.id, e.event_type, e.chain, e.score, e.status] for e in events]

    async def dashboard_stats_fn() -> str:
        return (
            "## WhaleDecode Dashboard\n\n"
            "**Status:** Running\n"
            f"**Chain Provider:** {type(chain).__name__}\n"
            f"**Investigation Model:** {settings.DEFAULT_STRONG_MODEL}\n\n"
            "Use the tabs below to browse wallets, investigate events, and chat with the AI agent."
        )

    with gr.Blocks(title="WhaleDecode", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🐋 WhaleDecode — AI Smart Money Agent")
        gr.Markdown("Monitor whale wallets, detect on-chain events, and investigate with AI.")

        with gr.Tab("Dashboard"):
            stats_btn = gr.Button("Refresh Dashboard", variant="primary")
            stats_out = gr.Markdown()
            stats_btn.click(fn=lambda: asyncio.run(dashboard_stats_fn()), outputs=stats_out)

        with gr.Tab("Wallets"):
            with gr.Row():
                chain_filter = gr.Dropdown(choices=["All", "ETH", "BASE", "ARB"], label="Chain Filter", value="All")
                refresh_wallets = gr.Button("Refresh")
            wallet_table = gr.Dataframe(headers=["ID", "Address", "Chain", "Label", "Score"], interactive=False)
            refresh_wallets.click(fn=lambda c: asyncio.run(wallet_list_fn(c)), inputs=chain_filter, outputs=wallet_table)

        with gr.Tab("Events"):
            refresh_events = gr.Button("Refresh Events")
            event_table = gr.Dataframe(headers=["ID", "Type", "Chain", "Score", "Status"], interactive=False)
            refresh_events.click(fn=lambda: asyncio.run(event_list_fn()), outputs=event_table)

        with gr.Tab("AI Chat"):
            gr.Markdown("Ask the investigation agent about wallets, transactions, or market movements.")
            chatbot = gr.Chatbot(label="Conversation")
            msg = gr.Textbox(label="Your message", placeholder="Ask about a wallet or event...")
            gr.ClearButton([msg, chatbot])

            async def respond(message: str, history: list) -> tuple[str, list]:
                history = history or []
                response = await investigation.chat(message)
                history.append([message, response])
                return "", history

            msg.submit(respond, [msg, chatbot], [msg, chatbot])

    return app
