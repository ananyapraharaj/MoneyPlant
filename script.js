// ✅ Replace with your own Supabase credentials
const SUPABASE_URL = 'https://osmirjtgigrcrkzzhngj.supabase.co/';
const SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9zbWlyanRnaWdyY3JrenpobmdqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTQzNzE4ODUsImV4cCI6MjA2OTk0Nzg4NX0.zMIpS_TywokR16NWg_92Ay8aqC47Qdbj8FdXBa2Ct2s';

const client = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);


document.getElementById("paymentForm").addEventListener("submit", async function(event) {
  event.preventDefault();

  const amount = document.getElementById("amount").value;
  const title = document.getElementById("title").value;
  const due_date = document.getElementById("due_date").value;

  // Insert data into Supabase
  const { data, error } = await client
    .from('PAYMENT REMINDERS')
    .insert([
      {
        title: title,
        amount: parseFloat(amount),
        due_date: due_date
      }
    ]);
  console.log('Data:', data);
  console.log('Error:', error);


  const confirmation = document.getElementById("confirmation");

  if (error) {
    confirmation.innerText = `❌ Failed to save: ${error.message}`;
    console.error(error);
  } else {
    confirmation.innerText = `✅ Reminder saved for ₹${amount} to ${title} due on ${due_date}`;
    console.log(data);
  }
});


  