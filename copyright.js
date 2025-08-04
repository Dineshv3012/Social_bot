const express = require('express');
const router = express.Router();

router.post('/check', async (req, res) => {
  const { url, platform } = req.body;
  
  // Simulate copyright check
  const isCopyrighted = Math.random() > 0.5; // 50% chance for demo
  
  res.json({
    url,
    platform,
    isCopyrighted,
    details: isCopyrighted 
      ? 'This video contains copyrighted material'
      : 'No copyright issues detected'
  });
});

module.exports = router;