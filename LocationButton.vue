<template>
  <button 
    @click="handleClick"
    :disabled="isLoading"
    class="share-btn"
  >
    <span v-if="!isLoading">
      <LocationIcon />
      Share Location
    </span>
    <span v-else>Mengirim...</span>
  </button>
</template>

<script>
import LocationIcon from './icons/LocationIcon.vue';

export default {
  components: { LocationIcon },
  data() {
    return {
      isLoading: false
    };
  },
  methods: {
    async handleClick() {
      this.isLoading = true;
      
      try {
        const position = await this.getPosition();
        await saveLocation(position.coords.latitude, position.coords.longitude);
        this.$emit('success');
      } catch (error) {
        this.$emit('error', this.parseError(error));
      } finally {
        this.isLoading = false;
      }
    },
    getPosition() {
      return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
          reject(new Error('UNSUPPORTED'));
        }
        
        navigator.geolocation.getCurrentPosition(
          resolve,
          err => reject(err),
          { timeout: 10000 }
        );
      });
    },
    parseError(error) {
      const errors = {
        1: 'Aktifkan GPS di pengaturan perangkat Anda',
        2: 'Lokasi tidak terdeteksi - pastikan sinyal baik',
        3: 'Proses terlalu lama - cek koneksi internet',
        UNSUPPORTED: 'Browser tidak mendukung geolokasi'
      };
      return errors[error.code] || error.message;
    }
  }
};
</script>

<style scoped>
.share-btn {
  background: #4CAF50;
  color: white;
  padding: 12px 24px;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.3s;
}

.share-btn:disabled {
  background: #cccccc;
  cursor: not-allowed;
}

.share-btn:hover:not(:disabled) {
  background: #45a049;
  transform: translateY(-2px);
}
</style>
