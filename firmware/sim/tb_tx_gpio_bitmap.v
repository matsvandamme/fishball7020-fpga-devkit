// Self-checking testbench for tx_gpio_bitmap.
//
// Checks the module against a golden model written from the specification
// rather than from the implementation:
//
//   * flag = 0  -> the pins mirror the EMIO GPIO inputs, output enables and
//                  all, so Linux still owns them.
//   * flag = 1  -> the pins carry the sample nibble captured on the last
//                  clock where sample_valid was high, and are all driven
//                  (pin_t = 0).
//   * the flag crosses two flip-flops, so a change takes effect two clocks
//     later - stated here so that a one-stage (metastability-prone) or
//     zero-stage version is a test failure and not a silent difference.
//
// The check that earns its keep is GAPPED VALID. On this board the transmit
// datapath presents a new sample every second l_clk in 2R2T mode. A nibble
// captured every clock instead of every sample doubles the rate of every
// pattern the user authored - a clock at Fs/2 instead of Fs/4, a frame marker
// one sample wide arriving twice. That looks perfect in a back-to-back
// simulation and costs a Vivado rebuild and a flash to discover on hardware.
//
//   run from firmware/:  ./sim/run_sim.sh

`timescale 1ns/100ps

module tb_tx_gpio_bitmap;

  localparam integer N = 4;

  reg              clk = 1'b0;
  reg              rst = 1'b1;
  reg  [N-1:0]     sample = 0;
  reg              sample_valid = 1'b0;
  reg              flag = 1'b0;
  reg  [N-1:0]     gpio_o_in = 0;
  reg  [N-1:0]     gpio_t_in = {N{1'b1}};
  wire [N-1:0]     pin_o;
  wire [N-1:0]     pin_t;

  integer errors = 0;
  integer checks = 0;
  integer i;

  always #5 clk = ~clk;

  tx_gpio_bitmap #(.NBITS(N)) dut (
    .clk(clk), .rst(rst),
    .sample(sample), .sample_valid(sample_valid), .flag(flag),
    .gpio_o_in(gpio_o_in), .gpio_t_in(gpio_t_in),
    .pin_o(pin_o), .pin_t(pin_t));

  // -- golden model -------------------------------------------------------
  // Independent state: what the pins are supposed to show.

  reg [N-1:0] gold_held = 0;   // last nibble accepted on a valid sample
  reg [1:0]   gold_flag = 2'b00;

  always @(posedge clk) begin
    if (rst == 1'b1) begin
      gold_held <= 0;
      gold_flag <= 2'b00;
    end else begin
      if (sample_valid == 1'b1) gold_held <= sample;
      gold_flag <= {gold_flag[0], flag};
    end
  end

  wire [N-1:0] gold_o = gold_flag[1] ? gold_held  : gpio_o_in;
  wire [N-1:0] gold_t = gold_flag[1] ? {N{1'b0}}  : gpio_t_in;

  task automatic check(input [255:0] what);
    begin
      checks = checks + 1;
      if (pin_o !== gold_o || pin_t !== gold_t) begin
        errors = errors + 1;
        $display("  FAIL %0s: pin_o=%b (want %b)  pin_t=%b (want %b)  t=%0t",
                 what, pin_o, gold_o, pin_t, gold_t, $time);
      end
    end
  endtask

  // Advance one clock, driving stimulus away from the edge.
  task automatic step(input [N-1:0] s, input v, input f,
                      input [N-1:0] go, input [N-1:0] gt,
                      input [255:0] what);
    begin
      @(negedge clk);
      sample = s; sample_valid = v; flag = f; gpio_o_in = go; gpio_t_in = gt;
      @(posedge clk);
      #1 check(what);
    end
  endtask

  initial begin
    $display("tx_gpio_bitmap: pins follow EMIO GPIO when the flag is clear,");
    $display("                and the sample nibble when it is set");

    // --- reset -----------------------------------------------------------
    repeat (3) @(posedge clk);
    @(negedge clk) rst = 1'b0;

    // --- flag = 0: standard GPIO passthrough ------------------------------
    // Every combination of output value and tristate must reach the pins
    // untouched, including while samples are streaming past underneath.
    for (i = 0; i < 16; i = i + 1) begin
      step(i[N-1:0], 1'b1, 1'b0, i[N-1:0] ^ 4'hA, i[N-1:0],
           "gpio passthrough");
    end

    // --- flag = 1: the nibble reaches the pins -----------------------------
    step(4'h0, 1'b1, 1'b1, 4'h5, 4'hF, "flag rising, cycle 1");
    step(4'h0, 1'b1, 1'b1, 4'h5, 4'hF, "flag rising, cycle 2");
    for (i = 0; i < 16; i = i + 1) begin
      step(i[N-1:0], 1'b1, 1'b1, 4'h5, 4'hF, "nibble tracks sample");
    end

    // --- gapped valid ------------------------------------------------------
    // The pattern 0,1,0,1,... presented on alternate clocks (2R2T) must come
    // out as one transition per SAMPLE, held across the idle clock between.
    for (i = 0; i < 16; i = i + 1) begin
      step(i[0] ? 4'hF : 4'h0, 1'b1, 1'b1, 4'h5, 4'hF, "gapped: valid clock");
      step(4'hA,               1'b0, 1'b1, 4'h5, 4'hF, "gapped: idle clock");
    end

    // --- a long idle: the last nibble is held, not cleared -----------------
    step(4'h9, 1'b1, 1'b1, 4'h5, 4'hF, "hold: load 9");
    for (i = 0; i < 8; i = i + 1) begin
      step(4'h6, 1'b0, 1'b1, 4'h5, 4'hF, "hold: still 9");
    end
    if (pin_o !== 4'h9) begin
      errors = errors + 1;
      $display("  FAIL hold: pin_o=%b after idle, want 1001", pin_o);
    end
    checks = checks + 1;

    // --- back to GPIO ------------------------------------------------------
    step(4'h3, 1'b1, 1'b0, 4'hC, 4'h0, "flag falling, cycle 1");
    step(4'h3, 1'b1, 1'b0, 4'hC, 4'h0, "flag falling, cycle 2");
    for (i = 0; i < 8; i = i + 1) begin
      step(i[N-1:0], 1'b1, 1'b0, i[N-1:0], ~i[N-1:0], "gpio again");
    end

    // --- reset while the flag is set ---------------------------------------
    step(4'hF, 1'b1, 1'b1, 4'h0, 4'hF, "before reset 1");
    step(4'hF, 1'b1, 1'b1, 4'h0, 4'hF, "before reset 2");
    @(negedge clk) rst = 1'b1;
    @(posedge clk);
    #1 check("reset returns the pins to GPIO");
    @(negedge clk) rst = 1'b0;

    $display("");
    if (errors == 0) $display("  PASS  %0d checks", checks);
    else             $display("  FAIL  %0d of %0d checks", errors, checks);
    $finish;
  end

endmodule
