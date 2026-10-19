class InitializeResearchStorageMiddleware:
    """Prepare existing research tables before any Django view, including admin."""

    sync_capable = False
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response

    async def __call__(self, request):
        from tracereview_web.research.views import _ensure_storage

        await _ensure_storage()
        return await self.get_response(request)
