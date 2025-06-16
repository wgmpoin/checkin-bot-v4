import { registerRoute } from 'workbox-routing';
import { NetworkFirst, CacheFirst } from 'workbox-strategies';
import { Queue } from 'workbox-background-sync';

// Queue untuk failed requests
const locationQueue = new Queue('locationQueue', {
  onSync: async ({ queue }) => {
    let entry;
    while (entry = await queue.shiftRequest()) {
      try {
        await fetch(entry.request);
        console.log('Replay successful for', entry.request.url);
      } catch (error) {
        await queue.unshiftRequest(entry);
        throw error;
      }
    }
  }
});

// Tangkap failed POST requests
registerRoute(
  /\/api\/locations/,
  async ({ event }) => {
    try {
      return await fetch(event.request);
    } catch (error) {
      await locationQueue.pushRequest({ request: event.request });
      return Response.error();
    }
  },
  'POST'
);

// Cache untuk assets
registerRoute(
  /\.(?:js|css|png|svg)$/,
  new CacheFirst({
    cacheName: 'assets-cache'
  })
);
